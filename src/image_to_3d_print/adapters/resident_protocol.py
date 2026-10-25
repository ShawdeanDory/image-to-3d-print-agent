"""模型环境和服务环境共享的纯标准库IPC协议；不含模型、API或任意命令。"""
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import UUID

PROTOCOL = 'trellis-resident-v1'
MAX_MESSAGE = 32768


def process_identity(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def receive_message(connection):
    data = bytearray()
    while b'\n' not in data:
        part = connection.recv(min(4096, MAX_MESSAGE + 1 - len(data)))
        if not part:
            raise ConnectionError('IPC连接提前关闭')
        data.extend(part)
        if len(data) > MAX_MESSAGE:
            raise ValueError('IPC消息过大')
    line, extra = bytes(data).split(b'\n', 1)
    if extra:
        raise ValueError('每连接只接受一个请求')
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError('IPC请求必须是对象')
    return value


def send_message(connection, value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'
    if len(data) > MAX_MESSAGE:
        raise ValueError('IPC消息过大')
    connection.sendall(data)


def validate_request(value, storage, revision):
    required = {'protocol', 'request_id', 'run_id', 'requester_pid', 'requester_identity', 'upstream_revision',
                'input', 'input_sha256', 'output', 'export_target_faces', 'texture_size', 'gpu_hole_repair'}
    if set(value) != required or value['protocol'] != PROTOCOL or value['upstream_revision'] != revision:
        raise ValueError('IPC字段/协议/源码版本不匹配')
    UUID(value['request_id']); run = str(UUID(value['run_id']))
    if type(value['requester_pid']) is not int or value['requester_pid'] <= 0 or not isinstance(value['requester_identity'], str):
        raise ValueError('请求进程身份无效')
    storage = Path(storage).resolve()
    source = Path(value['input']).resolve()
    output = Path(value['output']).resolve()
    if not source.is_relative_to(storage) or not source.is_file() or not output.is_relative_to(storage):
        raise ValueError('模型文件引用越界或缺失')
    parts = output.relative_to(storage).parts
    if len(parts) != 4 or parts[:3] != ('runs', run, 'tools') or not re.fullmatch(r't_[a-zA-Z0-9_-]+', parts[3]) or not output.is_dir():
        raise ValueError('输出不属于本任务工具目录')
    if (output / 'model.json').exists() or (output / 'fast_export.glb').exists():
        raise ValueError('禁止覆盖已有模型或重复执行同一输出')
    digest = value['input_sha256']
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('输入摘要格式错误')
    with source.open('rb') as stream:
        actual = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            actual.update(chunk)
        if actual.hexdigest() != digest:
            raise ValueError('输入摘要不匹配')
    for name, minimum, maximum in [('export_target_faces', 100, 1000000), ('texture_size', 256, 4096)]:
        if value[name] is not None and (type(value[name]) is not int or not minimum <= value[name] <= maximum):
            raise ValueError('模型导出参数越界')
    if type(value['gpu_hole_repair']) is not bool:
        raise ValueError('GPU补片开关必须是布尔值')
    return {**value, 'input': source, 'output': output}
