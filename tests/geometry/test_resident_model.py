"""模型驻留协议/进程固定检查；替身不是GPU模型证据。"""
from pathlib import Path
import hashlib
import os
from uuid import uuid4
import pytest
from pydantic import ValidationError
from image_to_3d_print.adapters.reconstruction import BackendConfig


def test_resident_trellis_configuration_is_explicit():
    config = BackendConfig(backend='trellis2_candidate', python=Path('python'), execution_root=Path('.'),
                           inference_profile='course_fast', execution_mode='resident')
    assert config.execution_mode == 'resident'
    with pytest.raises(ValidationError):
        BackendConfig(backend='triposr', python=Path('python'), execution_root=Path('.'), execution_mode='resident')


def valid_request(tmp_path):
    from image_to_3d_print.adapters.resident_protocol import PROTOCOL, process_identity
    run=str(uuid4()); source=tmp_path/'image.png';source.write_bytes(b'fixed-image-fixture')
    output=tmp_path/'runs'/run/'tools'/'t_fixture';output.mkdir(parents=True)
    return {'protocol':PROTOCOL,'request_id':str(uuid4()),'run_id':run,'requester_pid':os.getpid(),
            'requester_identity':process_identity(os.getpid()) or 'windows_fixture','upstream_revision':'fixed-revision',
            'input':str(source),'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'output':str(output),
            'export_target_faces':100000,'texture_size':2048,'gpu_hole_repair':False}


def test_resident_request_is_bound_to_real_input_and_task(tmp_path, monkeypatch):
    from image_to_3d_print.adapters.resident_protocol import validate_request
    # TRELLIS.2的Python3.10没有file_digest；共享协议不得依赖它。
    monkeypatch.delattr(hashlib, 'file_digest', raising=False)
    value=valid_request(tmp_path)
    result=validate_request(value,tmp_path,'fixed-revision')
    assert result['input'].read_bytes()==b'fixed-image-fixture'
    for change in [{'output':str(tmp_path/'..'/'outside')},{'run_id':str(uuid4())},
                   {'input_sha256':'0'*64},{'export_target_faces':True},{'texture_size':4097},
                   {'gpu_hole_repair':1},{'upstream_revision':'other'},{'shell':'do-not-execute'}]:
        with pytest.raises((ValueError,TypeError)):
            validate_request({**value,**change},tmp_path,'fixed-revision')
    (result['output']/'model.json').write_text('{}')
    with pytest.raises(ValueError):validate_request(value,tmp_path,'fixed-revision')


def test_framed_protocol_rejects_extra_data_and_large_messages():
    import io
    from types import SimpleNamespace
    from image_to_3d_print.adapters.resident_protocol import receive_message
    for data in [b'{}\n{}\n',b'[]\n',b'x'*32769]:
        reader=SimpleNamespace(recv=io.BytesIO(data).read)
        with pytest.raises((ValueError,ConnectionError)):receive_message(reader)
