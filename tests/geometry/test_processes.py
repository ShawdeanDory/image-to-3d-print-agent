import json,os,sys,threading
from pathlib import Path
import pytest
from pydantic import ValidationError
from image_to_3d_print.adapters.reconstruction import BackendConfig,execute_worker,REVISIONS
from image_to_3d_print.geometry.commands import COMMANDS,ToolConfiguration
from image_to_3d_print.tools import ToolFailure

@pytest.mark.skipif(os.name!='posix',reason='Linux进程组验证')
def test_model_env_isolation(tmp_path,monkeypatch):
    config=BackendConfig(backend='triposr',python=Path(sys.executable),execution_root=tmp_path)
    monkeypatch.setenv('PYTHONPATH','forbidden_parent_test_deps')
    monkeypatch.setattr('subprocess.check_output',lambda *a,**k:REVISIONS['triposr']+'\n')
    script=tmp_path/'fake_worker.py';script.write_text("import json,os,pathlib;pathlib.Path(__file__).with_suffix('.json').write_text(json.dumps({'path':os.environ.get('PYTHONPATH')}))")
    (tmp_path/'image.png').write_bytes(b'fixture')
    execute_worker(config,'reconstruct',tmp_path/'image.png',tmp_path,script)
    assert json.loads(script.with_suffix('.json').read_text())['path'] is None

@pytest.mark.skipif(os.name!='posix',reason='Linux进程组验证')
@pytest.mark.parametrize('cancel',[False,True])
def test_timeout_and_cancel_stop_child(tmp_path,monkeypatch,cancel):
    config=BackendConfig(backend='triposr',python=Path(sys.executable),execution_root=tmp_path,timeout_s=.05)
    monkeypatch.setattr('subprocess.check_output',lambda *a,**k:REVISIONS['triposr']+'\n')
    script=tmp_path/'wait.py';script.write_text('import time;time.sleep(5)')
    (tmp_path/'image').write_bytes(b'fixture')
    event=threading.Event()
    if cancel:event.set()
    with pytest.raises(ToolFailure) as caught:execute_worker(config,'reconstruct',tmp_path/'image',tmp_path,script,event)
    assert caught.value.code==('STATE_CONFLICT' if cancel else 'TOOL_TIMEOUT')
    assert json.loads((tmp_path/'execution.json').read_text())['exit_code']!=0

def test_backend_configuration_cannot_switch():
    config=BackendConfig(backend='trellis2_candidate',python=Path('/python'),execution_root=Path('/root'))
    with pytest.raises(ValidationError):ToolConfiguration(backends={'triposr':config})

def test_command_rejects_unknown_and_paths():
    from uuid import uuid4
    with pytest.raises(ValidationError):COMMANDS.validate_python({'operation':'shell','run_id':str(uuid4()),'command':'ls'})
    with pytest.raises(ValidationError):COMMANDS.validate_python({'operation':'import_image','run_id':str(uuid4()),'source':'../private.png'})

@pytest.mark.skipif(os.name!='posix',reason='Linux进程组验证')
def test_interrupted_parent_reaps_process_group(tmp_path,monkeypatch):
    import subprocess,signal
    config=BackendConfig(backend='triposr',python=Path(sys.executable),execution_root=tmp_path)
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:REVISIONS['triposr']+'\n')
    original=subprocess.Popen;created=[]
    def tracked(*args,**kwargs):
        process=original(*args,**kwargs);created.append(process);return process
    monkeypatch.setattr(subprocess,'Popen',tracked)
    def interrupted(*args):raise KeyboardInterrupt()
    monkeypatch.setattr('time.sleep',interrupted)
    worker=tmp_path/'worker.py';worker.write_text('import time;time.sleep(5)')
    (tmp_path/'input.png').write_bytes(b'fixture')
    try:
        with pytest.raises(KeyboardInterrupt):execute_worker(config,'reconstruct',tmp_path/'input.png',tmp_path,worker)
        assert created[0].poll() is not None
    finally:
        if created and created[0].poll() is None:
            os.killpg(created[0].pid,signal.SIGKILL);created[0].wait()
