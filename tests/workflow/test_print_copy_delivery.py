"""打印副本接入；重建/Blender/原生修复替身标明test_fixture。"""
from pathlib import Path
import numpy as np
import pytest
from image_to_3d_print.jobs.service import TaskService
from image_to_3d_print.runtime_contracts import CreateTask
from image_to_3d_print.tools import digest,ToolFailure
from image_to_3d_print.geometry.core import load_mesh
from .test_automatic_generation import automatic
from .test_repaired_delivery import TexturedFixture
from .conftest import pump


def configured(setup_service):
    service,settings,request=automatic(setup_service)
    data=settings.model_dump();data['tools']['print_repair']={'native_python':Path('unused-test-fixture'),'native_paths':[Path('unused-test-fixture')]}
    # 从实际服务端契约加载，不能由客户端注入工具路径。
    settings=type(settings).model_validate(data)
    return TaskService(settings),settings,{**request,'height_value':120.}


def test_policy_snapshot_and_original_stl_binding(setup_service,monkeypatch):
    service,settings,request=configured(setup_service)
    tools=TexturedFixture(monkeypatch)
    run=service.create(CreateTask(request=request),'same')['run_id']
    ctx=service.store.row(run)['context']
    assert ctx['delivery_policy']=='print-copy-color-v1' and not ctx.get('gpu_hole_policy')
    row=pump(service,settings,run,tools);assert row['status']=='succeeded',row['context'].get('error')
    delivery=row['response']['delivery'];assert delivery['geometry_policy']=='print_copy_color'
    assert delivery['print_certified'] is False
    artifacts={a['artifact_id']:a for a in row['response']['artifacts']}
    stl=artifacts[delivery['stl_artifact_id']];glb=artifacts[delivery['artifact_id']]
    assert stl['mesh_version']==glb['mesh_version']==delivery['mesh_version']
    np.testing.assert_allclose(load_mesh(settings.root/stl['relative_path']).extents,load_mesh(settings.root/glb['relative_path']).extents,atol=.01)
    from image_to_3d_print.geometry.glb_preserve import GLBDocument
    exported=GLBDocument(settings.root/glb['relative_path'])
    assert exported.has_uv and exported.tree.get('images')
    assert exported.material_signature()==GLBDocument(tools.original).material_signature()
    original=artifacts[delivery['original_artifact_id']]
    assert digest(settings.root/original['relative_path'])==tools.original_sha
    assert tools.calls.count('reconstruct')==1 and tools.calls.count('export_print_color')==1
    assert service.create(CreateTask(request=request),'same')['run_id']==run


@pytest.mark.parametrize('failure',['missing','shape'])
def test_native_failure_keeps_valid_files_and_explains_failure(setup_service,monkeypatch,failure):
    service,settings,request=configured(setup_service);tools=TexturedFixture(monkeypatch,mesh='open_cube.obj')
    def native(mesh,*args):
        if failure=='missing':raise ToolFailure('TOOL_UNAVAILABLE','test_fixture缺原生依赖')
        candidate=mesh.copy();candidate.apply_scale(.5)
        return candidate,{'evidence_origin':'test_fixture'}
    monkeypatch.setattr('image_to_3d_print.print_demo.native_call',native)
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,tools)
    assert row['status']=='succeeded',row['context'].get('error')
    delivery=row['response']['delivery']
    assert delivery['print_check']!='passed' and delivery['repair_attempts']==1
    assert any('打印副本修复失败' in w for w in delivery['warnings'])
    assert digest(tools.original)==tools.original_sha and tools.calls.count('reconstruct')==1


def test_two_round_limit_with_failed_thickness(setup_service,monkeypatch):
    service,settings,request=configured(setup_service);tools=TexturedFixture(monkeypatch,thin=True)
    phases=[]
    def native(mesh,directory,phase,*args):
        phases.append(phase);return mesh.copy(),{'evidence_origin':'test_fixture','phase':phase}
    monkeypatch.setattr('image_to_3d_print.print_demo.native_call',native)
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,tools)
    assert row['status']=='succeeded',row['context'].get('error')
    assert phases==[1,2] and row['response']['delivery']['repair_attempts']==2
    assert row['response']['delivery']['print_check']=='failed'
    assert row['context']['pending'] is None and tools.calls.count('reconstruct')==1


def test_schema_rejects_wrong_stl_and_original_references(setup_service,monkeypatch):
    from image_to_3d_print.runtime_contracts import GenerationTaskResponse
    from pydantic import ValidationError
    service,settings,request=configured(setup_service);tools=TexturedFixture(monkeypatch)
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,tools)
    for field in ['stl_artifact_id','original_artifact_id']:
        response=GenerationTaskResponse.model_validate(row['response']).model_dump(mode='json')
        response['delivery'][field]=response['delivery']['artifact_id']
        with pytest.raises(ValidationError):GenerationTaskResponse.model_validate(response)


def test_native_tool_requires_server_policy_and_current_inspection(setup_service,monkeypatch):
    from image_to_3d_print.geometry.commands import dispatch
    service,settings,request=configured(setup_service);tools=TexturedFixture(monkeypatch)
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,tools)
    response=row['response'];v=response['delivery']['mesh_version']
    command={'run_id':run,'operation':'repair_print_copy','mesh_version':v,'reference_version':v,'phase':1,
        'inspection':response['data']['inspection'],'height_mm':120.,'min_wall_mm':1.2}
    result=dispatch(settings.root,command,settings.tools)
    assert not result.tool.succeeded and result.tool.error.code=='STATE_CONFLICT'
    command['inspection']={**command['inspection'],'mesh_version':'m_'+'f'*24}
    result=dispatch(settings.root,command,settings.tools,automatic_action=True,confirmation_origin='automatic_policy')
    assert not result.tool.succeeded and result.tool.error.code=='STATE_CONFLICT'


def test_download_is_registered_stl_and_read_only(setup_service,monkeypatch):
    from image_to_3d_print.artifacts.stl import delivery_stl
    service,settings,request=configured(setup_service);tools=TexturedFixture(monkeypatch)
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,tools)
    delivery=row['response']['delivery'];stl=next(a for a in row['response']['artifacts'] if a['artifact_id']==delivery['stl_artifact_id'])
    payload,headers=delivery_stl(settings.root,run,row['response'],delivery['mesh_version'])
    assert payload==(settings.root/stl['relative_path']).read_bytes()
    assert headers['X-Print-Certified']=='false' and service.store.row(run)['response']==row['response']
