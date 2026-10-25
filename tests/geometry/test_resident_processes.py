"""Linux实际IPC/子进程验证；引擎明确为test_fixture，没有真实GPU结果。"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4
import pytest
from image_to_3d_print.adapters.reconstruction import BackendConfig,REVISIONS
from image_to_3d_print.adapters.resident import execute_resident
from image_to_3d_print.adapters.resident_protocol import PROTOCOL,process_identity,send_message
from image_to_3d_print.tools import ToolFailure

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Linux SO_PEERCRED和进程归属检查')


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """只允许本文件的本机Unix IPC；继续禁止TCP/公网。"""
    original=socket.socket.connect
    def connect(sock,address):
        if sock.family==socket.AF_UNIX and isinstance(address,str) and address.startswith('/tmp/i3d-test-'):
            return original(sock,address)
        raise AssertionError('驻留固定验证仅允许本机专用Unix套接字')
    monkeypatch.setattr(socket.socket,'connect',connect)


def start_server(tmp_path,delay=.01,owner=None):
    # /tmp短路径避免pytest生成的路径超过Unix socket上限。
    endpoint=Path('/tmp')/('i3d-test-'+uuid4().hex+'.sock')
    script=Path(__file__).with_name('resident_fixture_server.py')
    process=subprocess.Popen([sys.executable,str(script),'--socket',str(endpoint),'--storage',str(tmp_path),
        '--owner',str(owner or os.getpid()),'--delay',str(delay)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    deadline=time.monotonic()+5
    while not endpoint.exists():
        if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('固定服务未就绪')
        time.sleep(.02)
    return process,endpoint


def stop_server(process,endpoint):
    if process.poll() is None:process.terminate()
    process.wait(timeout=5);endpoint.unlink(missing_ok=True);endpoint.with_suffix('.json').unlink(missing_ok=True)


def request_paths(tmp_path,value=b'first'):
    run=str(uuid4());directory=tmp_path/'runs'/run/'tools'/('t_'+uuid4().hex[:8]);directory.mkdir(parents=True)
    source=tmp_path/('input-'+uuid4().hex+'.png');source.write_bytes(value)
    return source,directory


def config(tmp_path,endpoint,timeout=5):
    return BackendConfig(backend='trellis2_candidate',python=Path(sys.executable),execution_root=tmp_path,
                         inference_profile='course_fast',execution_mode='resident',resident_socket=endpoint,timeout_s=timeout)


def test_two_requests_reuse_one_process_but_consume_each_input(tmp_path):
    process,endpoint=start_server(tmp_path)
    try:
        reports=[]
        for data in [b'first',b'second']:
            source,output=request_paths(tmp_path,data)
            result=execute_resident(config(tmp_path,endpoint),source,output,REVISIONS['trellis2_candidate'])
            reports.append(json.loads((output/'model.json').read_text()))
            assert result['resident']['pid']==process.pid
        assert reports[0]['resident']['model_reused'] is False and reports[1]['resident']['model_reused'] is True
        assert reports[0]['input_sha256']!=reports[1]['input_sha256']
        assert reports[1]['calls']==2 and reports[1]['resident']['weight_load_count']==1
        assert reports[0]['resident']['instance_id']==reports[1]['resident']['instance_id']
    finally:stop_server(process,endpoint)


@pytest.mark.parametrize('cancel',[False,True])
def test_timeout_or_cancel_disconnect_reaps_resident(tmp_path,cancel):
    process,endpoint=start_server(tmp_path,delay=20)
    event=threading.Event()
    timer=threading.Timer(.2,event.set) if cancel else None
    if timer:timer.start()
    try:
        source,output=request_paths(tmp_path)
        with pytest.raises(ToolFailure) as error:
            execute_resident(config(tmp_path,endpoint,5 if cancel else .2),source,output,REVISIONS['trellis2_candidate'],event)
        assert error.value.code==('STATE_CONFLICT' if cancel else 'TOOL_TIMEOUT')
        process.wait(timeout=5)
        assert process.returncode==72
        assert not (output/'model.json').exists()
    finally:
        if timer:timer.cancel()
        stop_server(process,endpoint)


def test_idle_model_exits_if_owner_disappears(tmp_path):
    owner=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
    process,endpoint=start_server(tmp_path,owner=owner.pid)
    try:
        owner.terminate();owner.wait(timeout=5)
        process.wait(timeout=5)
        assert process.returncode==71
    finally:
        if owner.poll() is None:owner.terminate();owner.wait(timeout=5)
        stop_server(process,endpoint)


def test_model_exception_is_not_retried_and_process_exits(tmp_path):
    process,endpoint=start_server(tmp_path)
    try:
        source,output=request_paths(tmp_path,b'RAISE')
        with pytest.raises(ToolFailure) as error:execute_resident(config(tmp_path,endpoint),source,output,REVISIONS['trellis2_candidate'])
        assert error.value.code=='TOOL_UNAVAILABLE'
        process.wait(timeout=5)
        assert not (output/'model.json').exists()
    finally:stop_server(process,endpoint)
