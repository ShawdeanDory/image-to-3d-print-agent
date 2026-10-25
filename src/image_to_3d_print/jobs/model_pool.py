"""单worker拥有模型子进程；取消/超时/退出回收，下一任务才可重新冷启动。"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from ..adapters.reconstruction import REVISIONS
from ..adapters.resident_protocol import process_identity


class ResidentModels:
    def __init__(self, settings):
        self.settings = settings
        self.children = {}
        self.owner_identity = process_identity(os.getpid())
        self.backends = dict(settings.tools.backends)
        for name, config in list(self.backends.items()):
            if config.execution_mode != 'resident':
                continue
            if os.name != 'posix' or self.owner_identity is None:
                raise RuntimeError('模型常驻需要Linux单worker，不静默退回逐任务加载')
            folder = config.execution_root / 'runtime/resident'
            folder.mkdir(parents=True, exist_ok=True); folder.chmod(0o700)
            namespace = hashlib.sha256((str(settings.root.resolve()) + self.owner_identity).encode()).hexdigest()[:12]
            endpoint = folder / f'tr-{namespace}-{os.getpid()}.sock'
            if len(os.fsencode(endpoint)) >= 104:
                raise ValueError('模型IPC路径过长')
            self.backends[name] = config.model_copy(update={'resident_socket': endpoint})
        self.settings = settings.model_copy(update={'tools': settings.tools.model_copy(update={'backends': self.backends})})

    def ensure(self):
        for name, config in self.backends.items():
            if config.execution_mode != 'resident':
                continue
            previous = self.children.get(name)
            if previous and previous.poll() is None:
                continue
            if previous:
                self.stop(name)
            endpoint = config.resident_socket
            script = Path(__file__).resolve().parents[3] / 'scripts/tools/resident_model_worker.py'
            environment = dict(os.environ)
            for key in ['PYTHONPATH', 'PYTHONHOME', self.settings.llm.api_key_env, self.settings.api_token_env, 'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN']:
                environment.pop(key, None)
            environment.update(HF_HOME=str(config.execution_root/'runtime/cache/huggingface'), HF_HUB_OFFLINE='1',
                TRANSFORMERS_OFFLINE='1', CUDA_VISIBLE_DEVICES='0', OPENCV_IO_ENABLE_OPENEXR='1',
                PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True', OMP_NUM_THREADS='4')
            with endpoint.with_suffix('.log').open('ab') as log:
                process = subprocess.Popen([str(config.python), str(script), '--root', str(config.execution_root),
                    '--storage', str(self.settings.root), '--socket', str(endpoint), '--revision', REVISIONS[name],
                    '--owner-pid', str(os.getpid()), '--owner-identity', self.owner_identity],
                    stdout=log, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
            self.children[name] = process
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None or time.monotonic() > deadline:
                    self.stop(name)
                    raise RuntimeError('驻留模型监听未就绪；检查runtime/resident日志，不自动重试本任务')
                state_file = endpoint.with_suffix('.json')
                try:
                    state = json.loads(state_file.read_text())
                    if endpoint.exists() and state['pid'] == process.pid and state['owner_pid'] == os.getpid():
                        break
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(.05)

    def stop(self, name=None):
        names = [name] if name else list(self.children)
        for key in names:
            process = self.children.pop(key, None)
            if process is None:
                continue
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()
                except ProcessLookupError:
                    process.wait()
            self.backends[key].resident_socket.unlink(missing_ok=True)
