"""测试替身只替模型/Blender；几何、SQLite、LangGraph和GLB读回实际运行。"""
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient
from image_to_3d_print.api.app import create_app
from image_to_3d_print.jobs.config import Settings
from image_to_3d_print.jobs.service import TaskService
from image_to_3d_print.runtime_contracts import CreateTask
from image_to_3d_print.tools import ToolFailure
from .conftest import FixtureTools,pump


def automatic(setup_service):
    service,settings,request,_=setup_service
    settings=Settings.model_validate({**settings.model_dump(),'workflow_policy':'automatic_glb','confirmation_origin':'test_fixture'})
    service=TaskService(settings);request['orientation']={'up_axis':'z','confirmed':False}
    return service,settings,request


@pytest.mark.parametrize('thin',[False,True])
def test_one_submission_finishes_glb_even_when_print_check_fails(setup_service,monkeypatch,thin):
    service,settings,request=automatic(setup_service)
    run=service.create(CreateTask(request=request,backend='triposr'),'one-submit')['run_id']
    tools=FixtureTools(monkeypatch,thin=thin)
    row=pump(service,settings,run,tools)
    response=row['response']
    assert row['status']=='succeeded' and response['schema_version']=='generation-v1'
    assert response['delivery']['print_check']==('failed' if thin else 'passed')
    assert response['delivery']['print_certified'] is False
    assert row['context']['pending'] is None and not row['context'].get('human_reviews')
    assert tools.calls.count('reconstruct')==1
    artifact=next(a for a in response['artifacts'] if a['artifact_id']==response['delivery']['artifact_id'])
    assert artifact['mesh_version']==response['data']['state']['mesh_version']
    import trimesh
    assert len(trimesh.load(settings.root/artifact['relative_path'],force='mesh').faces)>0
    assert not response['data']['request']['orientation']['confirmed']
    assert response['data']['slicer_confirmation'] is None


def test_incomplete_initial_parameters_are_rejected_before_queue(setup_service):
    service,settings,request=automatic(setup_service);request.pop('height_value')
    with pytest.raises(ToolFailure,match='首次提交'):service.create(CreateTask(request=request))


def test_mode_is_fixed_fast_and_not_an_extra_user_choice(setup_service):
    service,settings,request=automatic(setup_service)
    run=service.create(CreateTask(request=request,backend='trellis2_candidate'))['run_id']
    assert service.store.row(run)['context']['reconstruction_profile']=='course_fast'
    with pytest.raises(ToolFailure):service.create(CreateTask(request=request,backend='trellis2_candidate',reconstruction_profile='official'))


def test_hole_repair_has_automatic_origin_and_preserves_original(setup_service,monkeypatch):
    service,settings,request=automatic(setup_service)
    run=service.create(CreateTask(request=request))['run_id'];tools=FixtureTools(monkeypatch,mesh='open_cube.obj')
    row=pump(service,settings,run,tools)
    assert row['status']=='succeeded'
    assert row['response']['delivery']['print_check']=='passed'
    assert row['response']['delivery']['repair_attempts']==1
    from image_to_3d_print.geometry.core import MeshStore
    record=MeshStore(settings.root).get(run,row['context']['mesh_version'])
    assert record.parameters['confirmation']['origin']=='automatic_policy'
    assert not any(e['source_type']=='human' for e in row['response']['evidence'])
    assert (settings.root/'fixture-mesh.obj').exists()


def test_two_ineffective_repairs_stop_and_deliver_glb(setup_service,monkeypatch):
    service,settings,request=automatic(setup_service)
    monkeypatch.setattr('image_to_3d_print.geometry.structure._fill_small',lambda mesh,limit:(mesh.copy(),{'test_fixture':'unchanged repair'}))
    run=service.create(CreateTask(request=request))['run_id'];tools=FixtureTools(monkeypatch,mesh='open_cube.obj')
    row=pump(service,settings,run,tools)
    assert row['status']=='succeeded' and row['response']['delivery']['repair_attempts']==2
    assert row['response']['delivery']['print_check']=='failed'
    assert tools.calls.count('apply')==2 and row['context']['pending'] is None
    assert len(row['context']['inspection_history'])==3
    assert row['response']['delivery']['mesh_version']==row['context']['inspection_history'][0]['mesh_version']
    assert any('已达2轮' in w and 'boundary_edges=fail' in w for w in row['response']['delivery']['warnings'])
    report=next(a for a in row['response']['artifacts'] if a['kind']=='quality_report' and a['relative_path'].endswith('.md'))
    readable=(settings.root/report['relative_path']).read_text(encoding='utf-8')
    assert 'GLB生成完成' in readable and '打印检查：failed' in readable and '自动修复尝试：2轮' in readable


def test_missing_checker_remains_unknown_but_glb_is_delivered(setup_service,monkeypatch):
    service,settings,request=automatic(setup_service);tools=FixtureTools(monkeypatch)
    def missing(*a,**kw):raise ToolFailure('TOOL_UNAVAILABLE','TEST_FIXTURE missing checker')
    monkeypatch.setattr('image_to_3d_print.inspection.service.blender_call',missing)
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,tools)
    assert row['status']=='succeeded' and row['response']['delivery']['print_check']=='not_run'
    assert any(c['status']=='not_run' for c in row['context']['inspection']['checks'])


@pytest.mark.parametrize('operation',['reconstruct','export_glb'])
def test_missing_real_tool_does_not_fabricate_completed_delivery(setup_service,monkeypatch,operation):
    service,settings,request=automatic(setup_service);fixture=FixtureTools(monkeypatch)
    reached=[]
    def tools(root,command,config,**kw):
        if command['operation']==operation:
            reached.append(operation);raise ToolFailure('TOOL_UNAVAILABLE','TEST_FIXTURE unavailable')
        return fixture(root,command,config,**kw)
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,tools)
    assert row['status']=='failed' and row['response']['delivery'] is None
    assert reached==[operation] and row['response']['error']['code']=='TOOL_UNAVAILABLE'


def test_false_print_label_and_legacy_print_success_are_rejected(setup_service,monkeypatch):
    from pydantic import ValidationError
    from image_to_3d_print.runtime_contracts import GenerationTaskResponse
    from image_to_3d_print.schemas.task import ModelTaskResponse
    service,settings,request=automatic(setup_service);run=service.create(CreateTask(request=request))['run_id']
    value=pump(service,settings,run,FixtureTools(monkeypatch,thin=True))['response']
    with pytest.raises(ValidationError):ModelTaskResponse.model_validate(value)
    value['delivery']['print_check']='passed'
    with pytest.raises(ValidationError):GenerationTaskResponse.model_validate(value)


def test_automatic_permission_cannot_be_claimed_through_public_command(setup_service):
    from uuid import uuid4
    from image_to_3d_print.geometry.commands import dispatch,ToolConfiguration
    _,settings,_=automatic(setup_service)
    outcome=dispatch(settings.root,{'run_id':uuid4(),'operation':'confirm','proposal_id':'p_'+'a'*24,'reviewer':'fake_auto','accepted':True},ToolConfiguration(),confirmation_origin='automatic_policy')
    assert not outcome.tool.succeeded


def test_http_idempotency_refresh_and_cancel(setup_service):
    service,settings,request=automatic(setup_service)
    with TestClient(create_app(settings)) as client:
        config=client.get('/api/v1/configuration').json()
        assert config['workflow_policy']=='automatic_glb'
        body={'request':request,'backend':'triposr'}
        first=client.post('/api/v1/model-tasks',json=body,headers={'Idempotency-Key':'auto-retry'})
        second=client.post('/api/v1/model-tasks',json=body,headers={'Idempotency-Key':'auto-retry'})
        assert first.status_code<300 and first.json()['run_id']==second.json()['run_id']
        run=first.json()['run_id'];url=f'/api/v1/model-tasks/{run}'
        assert client.get(url).json()['schema_version']=='generation-v1'
        assert client.get(url+'/runtime').json()['pending'] is None
        assert client.post(url+'/cancel').json()['status']=='cancelled'


@pytest.mark.parametrize('operation',['reconstruct','inspect'])
def test_foreign_tool_evidence_stops_automatic_delivery(setup_service,monkeypatch,operation):
    from uuid import uuid4
    service,settings,request=automatic(setup_service);fixture=FixtureTools(monkeypatch)
    def tools(root,command,config,**kw):
        outcome=fixture(root,command,config,**kw)
        if command['operation']==operation:
            return outcome.model_copy(update={'tool':outcome.tool.model_copy(update={'run_id':uuid4()})})
        return outcome
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,tools)
    assert row['status']=='failed' and row['response']['error']['code']=='STATE_CONFLICT'
    assert row['response']['delivery'] is None


@pytest.mark.parametrize('kind',['timeout','restart'])
def test_automatic_worker_stops_without_repeating_reconstruction(setup_service,kind):
    from image_to_3d_print.jobs.worker import Worker
    from image_to_3d_print.workflow.state import save_context
    service,settings,request=automatic(setup_service)
    run=service.create(CreateTask(request=request))['run_id']
    if kind=='timeout':Worker(settings.model_copy(update={'active_timeout_s':.01})).serve(once=True)
    else:
        ctx=service.store.row(run)['context'];ctx.update(status='running',inflight='reconstruct',tool_calls=1)
        save_context(service.store,ctx);Worker(settings).recover_interrupted()
    row=service.store.row(run)
    assert row['status']=='failed' and row['response']['delivery'] is None
    assert row['context']['error']['code']==('TOOL_TIMEOUT' if kind=='timeout' else 'WORKER_RESTARTED')
    assert row['runner_pid'] is None
