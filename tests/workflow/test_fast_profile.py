from image_to_3d_print.runtime_contracts import CreateTask
from image_to_3d_print.jobs.store import Store
from fastapi.testclient import TestClient
from image_to_3d_print.api.app import create_app


def test_profile_is_saved_with_original_task_and_idempotency(setup_service):
    service,settings,request,_=setup_service
    body=CreateTask(request=request,backend='trellis2_candidate',reconstruction_profile='course_fast')
    first=service.create(body,'fast-fixed-input')
    assert service.create(body,'fast-fixed-input')['run_id']==first['run_id']
    row=Store(settings.root).row(first['run_id'])
    assert row['context']['reconstruction_profile']=='course_fast'
    assert row['context']['backend']=='trellis2_candidate'
    client=TestClient(create_app(settings))
    assert client.get(f"/api/v1/model-tasks/{first['run_id']}/runtime").json()['resources']['reconstruction'] is None
    rejected=client.post('/api/v1/model-tasks',json={**body.model_dump(mode='json'),'backend':'triposr'})
    assert rejected.status_code==422


def test_historical_tool_times_are_read_without_inventing_missing_stages(setup_service):
    from image_to_3d_print.workflow.state import save_context
    service,settings,request,_=setup_service
    created=service.create(CreateTask(request=request))
    ctx=service.store.row(created['run_id'])['context']
    ctx['operations']=[{'operation':'reconstruct','result':{'data':{'model':{
        'inference_profile':'official','seconds':{'inference':None,'total':12.5},'evidence_origin':'test_fixture'}}}}]
    save_context(service.store,ctx)
    client=TestClient(create_app(settings))
    value=client.get(f"/api/v1/model-tasks/{created['run_id']}/runtime").json()['resources']['reconstruction']
    assert value['seconds']=={'inference':None,'total':12.5}


def test_old_idempotency_key_without_new_optional_field_keeps_same_task(setup_service):
    import json
    from image_to_3d_print.jobs.store import dumps
    service,settings,request,_=setup_service
    body=CreateTask(request=request)
    created=service.create(body,'historical-create')
    # 模拟升级前已保存的请求，不含新增可选profile；原任务不能被重新创建。
    with service.store.connect() as db:
        original=json.loads(db.execute('SELECT create_body FROM tasks WHERE run=?',(created['run_id'],)).fetchone()[0])
        original.pop('reconstruction_profile',None)
        db.execute('UPDATE tasks SET create_body=? WHERE run=?',(dumps(original),created['run_id']))
    assert service.create(body,'historical-create')['run_id']==created['run_id']
