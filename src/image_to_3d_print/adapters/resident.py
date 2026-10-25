"""调用worker持有的单个驻留模型；失败不切换模型、不自动重试。"""
import json
import os
from pathlib import Path
import socket
import time
from uuid import uuid4
from .resident_protocol import PROTOCOL, process_identity, send_message
from ..tools import ToolFailure, digest


def execute_resident(config, input_path, output, revision, cancel_event=None):
    endpoint = config.resident_socket
    if os.name != 'posix' or endpoint is None:
        raise ToolFailure('MODEL_NOT_CONFIGURED', '驻留模型需要Linux单worker提供的明确IPC端点')
    output = Path(output).resolve()
    request_id = str(uuid4())
    request = {'protocol': PROTOCOL, 'request_id': request_id, 'run_id': output.parents[1].name,
               'requester_pid': os.getpid(), 'requester_identity': process_identity(os.getpid()),
               'upstream_revision': revision, 'input': str(Path(input_path).resolve()),
               'input_sha256': digest(input_path), 'output': str(output),
               'export_target_faces': config.export_target_faces, 'texture_size': config.texture_size,
               'gpu_hole_repair': config.gpu_hole_repair}
    started = time.perf_counter()
    reply = None
    reason = None
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise ToolFailure('STATE_CONFLICT','任务已取消，不发送驻留推理请求')
        connection.settimeout(2)
        connection.connect(str(endpoint))
        send_message(connection, request)
        connection.settimeout(.1)
        data = bytearray()
        while b'\n' not in data:
            if cancel_event is not None and cancel_event.is_set():
                raise ToolFailure('STATE_CONFLICT', '任务已取消，驻留请求已断开')
            if time.perf_counter() - started > config.timeout_s:
                raise ToolFailure('TOOL_TIMEOUT', '驻留模型工具执行超时，请求已断开')
            try:
                part = connection.recv(4096)
            except socket.timeout:
                continue
            if not part:
                raise ToolFailure('TOOL_UNAVAILABLE', '驻留模型进程退出；本次任务不自动重试')
            data.extend(part)
            if len(data) > 32768:
                raise ToolFailure('TOOL_UNAVAILABLE', '驻留响应过大')
        reply = json.loads(bytes(data).split(b'\n', 1)[0])
        if reply.get('protocol') != PROTOCOL or reply.get('request_id') != request_id:
            raise ToolFailure('STATE_CONFLICT', '驻留响应不属于本次请求')
        if reply.get('status') != 'succeeded':
            code = reply.get('error', {}).get('code')
            if code not in {'INVALID_ARGUMENT', 'TOOL_UNAVAILABLE', 'GPU_OUT_OF_MEMORY', 'MODEL_NOT_CONFIGURED'}:
                code = 'TOOL_UNAVAILABLE'
            raise ToolFailure(code, reply.get('error', {}).get('message', '驻留模型执行失败'))
    except ToolFailure as exc:
        reason = exc
    except (OSError, ValueError, KeyError, IndexError) as exc:
        reason = ToolFailure('TOOL_UNAVAILABLE', '驻留模型IPC未就绪或响应无效；不自动重试')
    finally:
        connection.close()
        execution = {'backend': config.backend, 'upstream_revision': revision,
                     'exit_code': 0 if reason is None else 1, 'exit_code_scope': 'resident_request_not_process_exit',
                     'process_exit_code': None, 'execution_mode': 'resident',
                     'process_wall_seconds': time.perf_counter() - started, 'process_wall_scope': 'resident_request',
                     'seed': 42, 'inference_profile': config.inference_profile, 'entry': 'resident_model_worker.py',
                     'machine': 'configured_linux_instance', 'device': config.device, 'offline': True,
                     'automatic_retries': 0, 'input_sha256': request['input_sha256'],
                     'resident': {key: reply.get(key) for key in ['instance_id', 'pid', 'request_index', 'server_request_seconds', 'model_reused']} if reply else None}
        (output / 'execution.json').write_text(json.dumps(execution, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        with (output / 'process.log').open('a', encoding='utf-8') as log:
            log.write(json.dumps({'resident_request': request_id, 'status': 'failed' if reason else 'succeeded', 'error': str(reason) if reason else None}, ensure_ascii=False) + '\n')
    if reason:
        raise reason
    return execution
