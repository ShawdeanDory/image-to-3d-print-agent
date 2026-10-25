"""独立单worker；等待退出runner，重启不重跑中断中的昂贵节点。"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import psutil
from .config import Settings
from .store import Store
from .processes import SingleWorker, kill_tree, stop_owned_runner
from ..workflow.state import save_context, fail
from ..reports.quality import write_quality
from .model_pool import ResidentModels


class Worker:
    def __init__(self, settings):
        self.settings = settings.model_copy(update={'root': settings.root.resolve()})
        self.store = Store(self.settings.root)
        self.stopping = False
        self.models = ResidentModels(self.settings)
        self.settings = self.models.settings

    def recover_interrupted(self):
        with self.store.connect() as db:
            runs = [r['run'] for r in db.execute("SELECT run FROM tasks WHERE status IN ('running','cancel_requested')")]
        for run in runs:
            row = self.store.row(run)
            stop_owned_runner(row)
            ctx = row['context']
            ctx['interrupted_active_seconds_unknown'] = True
            if ctx['llm']['reserved_tokens']:
                ctx['llm']['usage_complete'] = False
                if ctx['llm']['records']: ctx['llm']['records'][-1]['status'] = 'interrupted_usage_unknown'
            if row['status'] == 'cancel_requested': ctx.update(status='cancelled', pending=None, error=None)
            else: fail(ctx, 'WORKER_RESTARTED', 'worker重启，中断中的计算未自动重跑；请核对已有产物后创建新任务')
            write_quality(self.store, ctx)
            save_context(self.store, ctx, 'worker_restarted')

    def run_once(self):
        row = self.store.claim()
        if row is None: return False
        try:
            self.models.ensure()
        except (OSError, RuntimeError, ValueError):
            ctx=row['context']
            fail(ctx,'MODEL_NOT_CONFIGURED','驻留模型监听未就绪，本次任务停止、不自动重试')
            write_quality(self.store,ctx)
            save_context(self.store,ctx,'resident_unavailable')
            return True
        run = row['run']
        remaining = self.settings.active_timeout_s - row['active_seconds']
        ctx = row['context']
        if remaining <= 0:
            fail(ctx, 'TOOL_TIMEOUT', '任务累计活动时间已达上限')
            write_quality(self.store, ctx)
            save_context(self.store, ctx, 'timeout')
            return True
        config = self.store.root / 'worker-config.json'
        config.write_text(self.settings.model_dump_json(indent=2), encoding='utf-8')
        directory = self.store.root / 'runs' / run
        directory.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        reason = None
        with (directory / 'runner.log').open('ab') as log:
            command = [sys.executable, '-m', 'image_to_3d_print.jobs.runner', '--config', str(config), '--run', run,
                '--parent-pid', str(os.getpid()), '--parent-birth', str(psutil.Process().create_time())]
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=os.name == 'posix')
            birth = psutil.Process(process.pid).create_time()
            with self.store.connect() as db:
                db.execute('UPDATE tasks SET runner_pid=?,runner_birth=? WHERE run=?', (process.pid, birth, run))
            try:
                while process.poll() is None:
                    current = self.store.row(run)
                    status = current['status']
                    if status == 'cancel_requested': reason = 'cancelled'
                    elif self.stopping: reason = 'restart'
                    elif time.perf_counter() - started >= remaining: reason = 'timeout'
                    elif current['context'].get('llm_deadline_monotonic', float('inf')) <= time.monotonic(): reason = 'llm_timeout'
                    if reason:
                        self.models.stop()
                        kill_tree(process.pid)
                        process.wait(timeout=10)
                        break
                    time.sleep(.05)
            except BaseException:
                self.models.stop()
                kill_tree(process.pid)
                process.wait(timeout=10)
                raise
        elapsed = time.perf_counter() - started
        with self.store.connect() as db:
            db.execute('UPDATE tasks SET active_seconds=active_seconds+?,runner_pid=NULL,runner_birth=NULL WHERE run=?', (elapsed, run))
        row = self.store.row(run)
        ctx = row['context']
        if reason or process.returncode or row['status'] in {'running', 'cancel_requested'}:
            self.models.stop()
            if reason == 'cancelled' or row['status'] == 'cancel_requested': ctx.update(status='cancelled', pending=None, error=None)
            elif reason == 'timeout': fail(ctx, 'TOOL_TIMEOUT', '任务累计活动时间超时，计算进程树已停止')
            elif reason == 'llm_timeout': fail(ctx, 'TOOL_TIMEOUT', '语言模型总请求超时，计算进程树已停止')
            elif reason == 'restart': fail(ctx, 'WORKER_RESTARTED', 'worker停止，计算进程树已回收，不自动重跑')
            else: fail(ctx, 'TOOL_UNAVAILABLE', '任务子进程异常退出，已有产物保留')
            if ctx['llm']['reserved_tokens']:
                ctx['llm']['usage_complete'] = False
                if ctx['llm']['records']: ctx['llm']['records'][-1]['status'] = 'interrupted_usage_unknown'
            write_quality(self.store, ctx)
            save_context(self.store, ctx, 'worker_stopped')
        elif row['status'] in {'failed','cancelled'}:
            self.models.stop()
        return True

    def queue_automatic_input_reviews(self):
        """仅接续旧图片等待；不批准姿态、结构修改或切片，不创建人工提交。"""
        if self.settings.input_review_policy!='automatic':return
        with self.store.transaction() as db:
            runs=[r['run'] for r in db.execute("SELECT run FROM tasks WHERE status='waiting_for_input'")]
            for run in runs:
                row=self.store.row(run,db);ctx=row['context']
                if (ctx.get('pending') or {}).get('kind')!='input_review':continue
                db.execute("UPDATE tasks SET status='queued' WHERE run=?",(run,))
                self.store.event(db,run,'input_policy_updated',ctx,{'policy':'automatic','origin':'tool'})

    def serve(self, once=False):
        with SingleWorker(self.store.root):
            try:
                self.models.ensure()
                self.recover_interrupted()
                self.queue_automatic_input_reviews()
                while not self.stopping:
                    worked = self.run_once()
                    if once: break
                    if not worked: time.sleep(.25)
            finally:
                self.models.stop()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    worker = Worker(Settings.from_env())
    def stop(*_): worker.stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker.serve(args.once)


if __name__ == '__main__': main()
