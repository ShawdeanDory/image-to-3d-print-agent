import importlib.util
import json
from pathlib import Path
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def test_launcher_contract_and_example():
    from image_to_3d_print.launcher_contracts import LauncherConfig, LauncherResult
    config = LauncherConfig.model_validate_json((ROOT/'config/launcher.example.json').read_text())
    assert config.ui_port != config.tunnel_port
    assert LauncherResult(status='succeeded',phase='ready').model_submitted is False


@pytest.mark.parametrize('value',[
    {'ssh_config':'../key'}, {'ssh_alias':'host;whoami'},
    {'remote_project':'/root/project;echo nope'}, {'deployment':'../../other'},
    {'ui_port':9000}, {'tunnel_port':80}, {'password':'not_allowed'},
])
def test_launcher_rejects_paths_commands_and_credentials(value):
    from image_to_3d_print.launcher_contracts import LauncherConfig
    with pytest.raises(ValidationError): LauncherConfig(**value)


def remote_helper():
    spec=importlib.util.spec_from_file_location('ensure_cloud_service',ROOT/'scripts/desktop_launcher/ensure_cloud_service.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_cloud_probe_rejects_foreign_health():
    helper=remote_helper()
    assert helper.is_our_api({'schema_version':'runtime-v1','configured_backends':['triposr']})
    assert not helper.is_our_api({'ok':True})


def test_cloud_helper_start_is_idempotent_with_fixture(tmp_path,monkeypatch):
    helper=remote_helper()
    project=tmp_path/'project';code=project/'deployments/current'
    (code/'scripts/tools').mkdir(parents=True)
    (code/'scripts/tools/start_cloud_backend.sh').write_text('# fixture')
    (project/'runtime/config').mkdir(parents=True)
    (project/'storage').mkdir()
    (project/'runtime/config/backend.json').write_text(json.dumps({'root':str(project/'storage')}))
    monkeypatch.setattr(helper,'probe_api',lambda:{'schema_version':'runtime-v1','configured_backends':['triposr']})
    monkeypatch.setattr(helper,'worker_running',lambda root:True)
    monkeypatch.setattr(helper,'start_component',lambda *a:pytest.fail('不能重复启动已有服务'))
    value=helper.ensure(project,code)
    assert value['api']=='already_running' and value['worker']=='already_running'
