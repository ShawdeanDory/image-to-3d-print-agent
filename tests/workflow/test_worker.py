import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import pytest
import psutil
from image_to_3d_print.jobs.worker import Worker
from image_to_3d_print.jobs.processes import SingleWorker, kill_tree
from image_to_3d_print.schemas.task import ModelTaskRequest
from image_to_3d_print.workflow.state import save_context


def create(service, request): return service.create(ModelTaskRequest.model_validate(request))['run_id']


def test_real_runner_waiting_releases_worker_and_two_tasks_serial(setup_service):
    service, settings, request, _ = setup_service
    request.pop('height_value')
    runs = [create(service, request), create(service, request)]
    worker = Worker(settings)
    with SingleWorker(service.store.root):
        for run in runs:
            assert worker.run_once()
            row = service.store.row(run)
            assert row['status'] == 'waiting_for_input', row['context'].get('error')
            assert row['runner_pid'] is None and row['active_seconds'] > 0
        assert not worker.run_once()
    for run in runs:
        assert service.store.row(run)['context']['tool_calls'] == 0


def test_single_worker_lock(setup_service):
    service, settings, request, _ = setup_service
    with SingleWorker(service.store.root):
        with pytest.raises(RuntimeError):
            with SingleWorker(service.store.root): pass


def test_actual_runner_timeout_stops_and_preserves(setup_service):
    service, settings, request, _ = setup_service
    run = create(service, request)
    Worker(settings.model_copy(update={'active_timeout_s': .01})).serve(once=True)
    row = service.store.row(run)
    assert row['status'] == 'failed' and row['context']['error']['code'] == 'TOOL_TIMEOUT'
    assert row['runner_pid'] is None
    assert any(a['kind'] == 'quality_report' for a in row['response']['artifacts'])


def test_actual_running_cancel_kills_runner(setup_service):
    service, settings, request, _ = setup_service
    run = create(service, request)
    worker = Worker(settings)
    thread = threading.Thread(target=worker.run_once)
    thread.start()
    deadline = time.monotonic() + 10
    while not service.store.row(run)['runner_pid'] and time.monotonic() < deadline: time.sleep(.01)
    service.cancel(run)
    thread.join(timeout=15)
    assert not thread.is_alive()
    assert service.store.row(run)['status'] == 'cancelled'
    assert service.store.row(run)['runner_pid'] is None


def test_restart_marks_active_failed_and_leaves_waiting_queued(setup_service):
    service, settings, request, _ = setup_service
    active, queued = create(service, request), create(service, request)
    ctx = service.store.row(active)['context']
    ctx.update(status='running', inflight='reconstruct')
    save_context(service.store, ctx)
    Worker(settings).recover_interrupted()
    assert service.store.row(active)['context']['error']['code'] == 'WORKER_RESTARTED'
    assert service.store.row(queued)['status'] == 'queued'
    assert service.store.row(active)['context']['tool_calls'] == 0


def test_process_tree_cleanup(tmp_path):
    marker = tmp_path / 'child.txt'
    child_code = 'import time; time.sleep(60)'
    code = f'import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,"-c",{child_code!r}]); pathlib.Path({str(marker)!r}).write_text(str(p.pid)); time.sleep(60)'
    process = subprocess.Popen([sys.executable, '-c', code])
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline: time.sleep(.01)
        child = int(marker.read_text())
        assert psutil.pid_exists(child)
        kill_tree(process.pid)
        process.wait(timeout=5)
        assert not psutil.pid_exists(child)
    finally:
        if process.poll() is None: kill_tree(process.pid)


def test_abrupt_worker_death_reaps_runner_and_never_replays_llm(setup_service, monkeypatch):
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from image_to_3d_print.jobs.config import LLMConfig
    service, settings, request, _ = setup_service
    released = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            released.wait(10)
            self.close_connection = True
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = settings.model_copy(update={'llm': LLMConfig(
        base_url=f'http://127.0.0.1:{server.server_address[1]}', model='TEST_FIXTURE_SERVER')})
    path = settings.root / 'abrupt-config.json'
    path.write_text(settings.model_dump_json(), encoding='utf-8')
    request['description'] = 'TEST_FIXTURE：中断中的LLM不重放'
    run = create(service, request)
    environment = {**os.environ, 'I3D_CONFIG': str(path), 'I3D_LLM_API_KEY': 'fixture-key',
        'LANGCHAIN_TRACING_V2': 'false', 'LANGSMITH_TRACING': 'false'}
    environment.pop('I3D_LLM_BASE_URL', None)
    environment.pop('I3D_LLM_MODEL', None)
    process = subprocess.Popen([sys.executable, '-m', 'image_to_3d_print.jobs.worker'], env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while service.store.row(run)['context']['llm']['calls'] != 1 and time.monotonic() < deadline: time.sleep(.05)
        row = service.store.row(run)
        assert row['context']['llm']['calls'] == 1
        runner = row['runner_pid']
        assert runner and psutil.pid_exists(runner)
        process.kill()  # 只杀父worker，验证runner自身的父进程监视器。
        process.wait(timeout=5)
        deadline = time.monotonic() + 10
        while psutil.pid_exists(runner) and time.monotonic() < deadline:
            try:
                if psutil.Process(runner).status() == psutil.STATUS_ZOMBIE: break
            except psutil.NoSuchProcess: break
            time.sleep(.05)
        assert not psutil.pid_exists(runner) or psutil.Process(runner).status() == psutil.STATUS_ZOMBIE
        Worker(settings).recover_interrupted()
        ctx = service.store.row(run)['context']
        assert ctx['error']['code'] == 'WORKER_RESTARTED'
        assert ctx['llm']['calls'] == 1
        assert ctx['interrupted_active_seconds_unknown'] is True
        assert ctx['llm']['usage_complete'] is False
    finally:
        if process.poll() is None: kill_tree(process.pid)
        released.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
