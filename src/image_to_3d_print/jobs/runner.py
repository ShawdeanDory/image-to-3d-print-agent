"""仅由独立worker启动；进程退出即释放模型及GPU资源。"""
import argparse
import os
from pathlib import Path
import threading
import time
import psutil
from langsmith import tracing_context
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from .config import Settings
from .store import Store
from .processes import kill_tree
from ..workflow.graph import build_graph
from ..workflow.state import save_context, fail


def run_task(settings, run, parent_pid=None, parent_birth=None):
    store = Store(settings.root)
    done = threading.Event()
    def watch_parent():
        while not done.wait(.25):
            try:
                parent = psutil.Process(parent_pid)
                if abs(parent.create_time() - parent_birth) < .01 and parent.is_running(): continue
            except psutil.NoSuchProcess: pass
            # 父worker消失时终止本次子树；新worker会明确记录WORKER_RESTARTED。
            kill_tree(os.getpid(), include_parent=False)
            os._exit(71)
    if parent_pid: threading.Thread(target=watch_parent, daemon=True).start()
    try:
        row = store.row(run)
        ctx = row['context']
        config = {'configurable': {'thread_id': str(run)}, 'recursion_limit': 160}
        with SqliteSaver.from_conn_string(str(store.root / 'checkpoints.sqlite3')) as saver:
            graph = build_graph(settings.model_copy(update={'workflow_policy':ctx.get('workflow_policy','guided')}), store, saver)
            if ctx['status'] == 'waiting_for_input':
                answer = store.pending_submission(run, ctx['pending']['pending_input_id'])
                if answer is None and settings.input_review_policy=='automatic' and ctx['pending']['kind']=='input_review':
                    answer={'kind':'automatic_input','pending_input_id':ctx['pending']['pending_input_id']}
                if answer is None: raise ValueError('恢复缺少已持久化的人工输入')
                with tracing_context(enabled=False): graph.invoke(Command(resume=answer), config)
            else:
                ctx['status'] = 'running'
                with tracing_context(enabled=False): graph.invoke({'ctx': ctx}, config)
    except Exception:
        ctx = store.row(run)['context']
        fail(ctx, 'TOOL_UNAVAILABLE', '运行时异常，任务已停止；已有产物保留')
        save_context(store, ctx, 'runner_failed')
        raise
    finally: done.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--parent-birth', type=float, required=True)
    args = parser.parse_args()
    settings = Settings.model_validate_json(args.config.read_text(encoding='utf-8'))
    run_task(settings, args.run, args.parent_pid, args.parent_birth)


if __name__ == '__main__': main()
