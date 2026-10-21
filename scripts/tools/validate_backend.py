"""本机真实HTTP/worker验证；自动化fixture确认不作为真实人工或模型证据。"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    storage = output / 'storage'
    config = output / 'config.json'
    config.write_text(json.dumps({'root': str(storage), 'default_backend': 'triposr',
        'operator_name': 'test_fixture_automation', 'profile_files': [str(ROOT / 'fixtures/p1/printer_profile.json')]},
        ensure_ascii=False), encoding='utf-8')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    environment = {**os.environ, 'I3D_CONFIG': str(config), 'I3D_API_TOKEN': 'local-fixture-access',
        'LANGSMITH_TRACING': 'false', 'LANGCHAIN_TRACING_V2': 'false'}
    # 验证缺配置分支，不继承外部LLM设置/凭据发起真实请求。
    for name in ['I3D_LLM_BASE_URL', 'I3D_LLM_MODEL', 'I3D_LLM_API_KEY']: environment.pop(name, None)
    log = (output / 'processes.log').open('wb')
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'image_to_3d_print.api.app:create_app',
        '--factory', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=environment, stdout=log, stderr=log)
    worker = None
    started = time.perf_counter()
    summary = {'evidence_origin': 'local_http_fixture_automation', 'model_execution': 'not_run',
        'llm_execution': 'not_run', 'human_acceptance': 'not_run'}
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=5, trust_env=False,
                headers={'Authorization': 'Bearer local-fixture-access'}) as client:
            deadline = time.monotonic() + 20
            while True:
                try:
                    health = client.get('/api/v1/configuration')
                    if health.status_code == 200: break
                except httpx.TransportError: pass
                if time.monotonic() >= deadline: raise RuntimeError('本机API启动超时')
                time.sleep(.1)
            summary['configuration'] = health.json()
            image = ROOT / 'fixtures/p1/procedural/block.png'
            uploaded = client.post('/api/v1/assets', files={'file': ('block.png', image.read_bytes(), 'image/png')})
            uploaded.raise_for_status()
            request = {'image_asset_id': uploaded.json()['asset_id'], 'printer_profile_id': 'demo_v1'}
            runs = []
            for index in range(2):
                before = time.perf_counter()
                result = client.post('/api/v1/model-tasks', json=request, headers={'Idempotency-Key': f'fixture-{index}'})
                result.raise_for_status()
                runs.append(result.json()['run_id'])
                summary[f'create_{index}_seconds'] = time.perf_counter() - before
            worker = subprocess.Popen([sys.executable, '-m', 'image_to_3d_print.jobs.worker'],
                cwd=ROOT, env=environment, stdout=log, stderr=log)
            def wait(run, status):
                until = time.monotonic() + 30
                while time.monotonic() < until:
                    value = client.get(f'/api/v1/model-tasks/{run}/runtime').json()
                    if value['response']['status'] == status: return value
                    if value['response']['status'] == 'failed': raise RuntimeError(value['response']['error'])
                    time.sleep(.1)
                raise RuntimeError('本机fixture状态等待超时')
            for run in runs: wait(run, 'waiting_for_input')
            first = wait(runs[0], 'waiting_for_input')
            pending = first['pending']
            answer = {'kind': 'constraints', 'submission_id': 'local_fixture_scale',
                'pending_input_id': pending['pending_input_id'], 'height_value': 80., 'height_unit': 'mm',
                'scale_source': 'user_target', 'orientation': {'up_axis': 'z', 'confirmed': True}}
            result = client.post(f'/api/v1/model-tasks/{runs[0]}/inputs', json=answer)
            result.raise_for_status()
            duplicate = client.post(f'/api/v1/model-tasks/{runs[0]}/inputs', json=answer)
            duplicate.raise_for_status()
            reviewed = wait(runs[0], 'waiting_for_input')
            # 输入已排队时旧waiting不会由公共响应显示；必须观察新图片复核等待项。
            until = time.monotonic() + 30
            while reviewed['pending']['kind'] != 'input_review':
                if time.monotonic() > until: raise RuntimeError('未到达前景复核')
                time.sleep(.1)
                reviewed = client.get(f'/api/v1/model-tasks/{runs[0]}/runtime').json()
            summary['foreground_review_pending'] = reviewed['pending']
            for run in runs:
                result = client.post(f'/api/v1/model-tasks/{run}/cancel')
                result.raise_for_status()
                assert result.json()['status'] == 'cancelled'
            summary['runs'] = [client.get(f'/api/v1/model-tasks/{run}/runtime').json() for run in runs]
            summary['event_counts'] = [len(client.get(f'/api/v1/model-tasks/{run}/events').json()['events']) for run in runs]
            summary['passed'] = True
    finally:
        for process in [worker, server]:
            if process is not None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        log.close()
        summary['seconds'] = time.perf_counter() - started
        summary['service_processes_stopped'] = server.poll() is not None and (worker is None or worker.poll() is not None)
        (output / 'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'passed': summary['passed'], 'seconds': summary['seconds'],
        'services_stopped': summary['service_processes_stopped']}, ensure_ascii=False))


if __name__ == '__main__': main()
