import pytest
from fastapi.testclient import TestClient
from image_to_3d_print.adapters.reconstruction import BackendConfig
from image_to_3d_print.api.app import create_app
from image_to_3d_print.jobs.service import TaskService
from image_to_3d_print.jobs.worker import Worker
from image_to_3d_print.runtime_contracts import CreateTask
from image_to_3d_print.tools import ToolFailure


def test_trellis_only_new_tasks_keep_old_idempotent_task(setup_service):
    service, settings, request, _ = setup_service
    old = service.create(CreateTask(request=request), 'old-key')
    configs = {name: BackendConfig(backend=name, python='python', execution_root='.') for name in ['triposr','trellis2_candidate']}
    changed = settings.model_copy(update={'default_backend':'trellis2_candidate', 'new_task_backends':['trellis2_candidate'],
                                         'tools':settings.tools.model_copy(update={'backends':configs})})
    updated = TaskService(changed)
    assert updated.create(CreateTask(request=request), 'old-key')['run_id'] == old['run_id']
    assert updated.store.row(old['run_id'])['context']['backend'] == 'triposr'
    with pytest.raises(ToolFailure) as error:
        updated.create(CreateTask(request=request, backend='triposr'), 'new-key')
    assert error.value.code == 'MODEL_NOT_CONFIGURED'
    new = updated.create(CreateTask(request=request), 'new-trellis')
    assert updated.store.row(new['run_id'])['context']['backend'] == 'trellis2_candidate'
    configuration = TestClient(create_app(changed)).get('/api/v1/configuration').json()
    assert configuration['configured_backends'] == ['trellis2_candidate']
    assert list(configuration['backend_profiles']) == ['trellis2_candidate']


def test_resident_start_failure_finishes_claimed_task(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    created = service.create(CreateTask(request=request))
    worker = Worker(settings)
    def unavailable():
        raise RuntimeError('fixed_listener_fixture_unavailable')
    monkeypatch.setattr(worker.models, 'ensure', unavailable)
    assert worker.run_once()
    ctx = service.store.row(created['run_id'])['context']
    assert ctx['status'] == 'failed' and ctx['error']['code'] == 'MODEL_NOT_CONFIGURED'
