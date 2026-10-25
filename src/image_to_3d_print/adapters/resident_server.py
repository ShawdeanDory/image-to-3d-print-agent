"""串行Unix套接字模型服务；只由持有单worker锁的父进程启动。"""
import json
import os
from pathlib import Path
import select
import socket
import struct
import threading
import time
from uuid import uuid4
from .resident_protocol import PROTOCOL, process_identity, receive_message, send_message, validate_request


def serve_model(endpoint, storage, revision, owner_pid, owner_identity, engine_factory):
    endpoint = Path(endpoint)
    state_file = endpoint.with_suffix('.json')
    instance = str(uuid4())
    stopped = threading.Event()
    engine = None
    index = 0

    def state(phase):
        data = {'protocol': PROTOCOL, 'instance_id': instance, 'pid': os.getpid(),
                'identity': process_identity(os.getpid()), 'owner_pid': owner_pid,
                'phase': phase, 'request_index': index, 'model_loaded': bool(engine and engine.loaded)}
        if engine is not None:
            data.update(engine.resources())
        temporary = state_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(state_file)

    def owner_watch():
        while not stopped.wait(.1):
            if process_identity(owner_pid) != owner_identity:
                os._exit(71)

    threading.Thread(target=owner_watch, daemon=True).start()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    bound = False
    try:
        listener.bind(str(endpoint)); bound = True; endpoint.chmod(0o600)
        listener.listen(1); listener.settimeout(.3)
        state('waiting_for_first_request')
        while not stopped.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            active = threading.Event()
            raw = {}
            try:
                connection.settimeout(2)
                peer_pid, peer_uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                raw = receive_message(connection)
                request = validate_request(raw, storage, revision)
                if peer_uid != os.getuid() or request['requester_pid'] != peer_pid or request['requester_identity'] != process_identity(peer_pid):
                    raise ValueError('IPC请求进程身份不匹配')
            except (OSError, ValueError, KeyError, TypeError, ConnectionError) as exc:
                try:
                    send_message(connection, {'protocol': PROTOCOL, 'request_id': locals().get('raw', {}).get('request_id'),
                        'status': 'failed', 'error': {'code': 'INVALID_ARGUMENT', 'message': str(exc)}})
                except OSError:
                    pass
                connection.close()
                continue

            def client_watch():
                while not active.wait(.1):
                    if process_identity(peer_pid) != request['requester_identity']:
                        os._exit(72)
                    try:
                        readable, _, _ = select.select([connection], [], [], 0)
                        if readable and connection.recv(1, socket.MSG_PEEK) == b'':
                            os._exit(72)
                    except OSError:
                        os._exit(72)

            watcher = threading.Thread(target=client_watch, daemon=True)
            watcher.start()
            started = time.perf_counter(); index += 1
            fatal = False
            try:
                if engine is None:
                    engine = engine_factory()
                state('loading_or_running')
                report = engine(request, {'instance_id': instance, 'pid': os.getpid(), 'request_index': index})
                engine.release_temporary()
                reply = {'protocol': PROTOCOL, 'request_id': request['request_id'], 'status': 'succeeded',
                         'instance_id': instance, 'pid': os.getpid(), 'request_index': index,
                         'server_request_seconds': time.perf_counter() - started,
                         'model_reused': report['resident']['model_reused']}
                state('idle_cached')
            except Exception as exc:
                import traceback
                traceback.print_exc()
                code = 'GPU_OUT_OF_MEMORY' if 'out of memory' in str(exc).lower() else 'TOOL_UNAVAILABLE'
                reply = {'protocol': PROTOCOL, 'request_id': request['request_id'], 'status': 'failed',
                         'error': {'code': code, 'message': '驻留模型执行失败，进程将回收；本任务不自动重试'}}
                fatal = True
            finally:
                active.set()
                watcher.join(timeout=1)
            try:
                send_message(connection, reply)
            finally:
                connection.close()
            if fatal:
                break
    finally:
        stopped.set()
        listener.close()
        if bound:
            endpoint.unlink(missing_ok=True)
