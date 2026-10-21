from .conftest import pump, FixtureTools, review_print
from image_to_3d_print.schemas import ModelTaskRequest
from image_to_3d_print.jobs.worker import Worker
from image_to_3d_print.adapters.reconstruction import BackendConfig
from pathlib import Path


def test_automatic_picture_policy_reaches_print_review_without_human_image_record(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    settings = settings.model_copy(update={'input_review_policy': 'automatic'})
    tools = FixtureTools(monkeypatch)
    run = service.create(ModelTaskRequest.model_validate(request))['run_id']
    row = pump(service, settings, run, tools)
    assert row['context']['pending']['kind'] == 'print_review'
    assert tools.calls.count('reconstruct') == 1
    assert row['context']['input_review']['origin'] == 'automatic'
    assert not row['context'].get('human_reviews')
    assert any(e['source_type'] == 'tool' and '自动' in e['summary'] for e in row['context']['evidence'])
    review_print(service, run)
    pump(service, settings, run, tools)
    assert tools.calls.count('reconstruct') == 1


def test_missing_scale_still_waits(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    settings = settings.model_copy(update={'input_review_policy': 'automatic'})
    request.pop('height_value')
    run = service.create(ModelTaskRequest.model_validate(request))['run_id']
    tools = FixtureTools(monkeypatch)
    row = pump(service, settings, run, tools)
    assert row['context']['pending']['kind'] == 'constraints'
    assert 'reconstruct' not in tools.calls


def test_old_image_wait_can_resume_automatically_but_print_wait_is_preserved(setup_service, monkeypatch):
    service, manual, request, _ = setup_service
    tools=FixtureTools(monkeypatch)
    first=service.create(ModelTaskRequest.model_validate(request))['run_id']
    assert pump(service,manual,first,tools)['context']['pending']['kind']=='input_review'
    automatic=manual.model_copy(update={'input_review_policy':'automatic'})
    Worker(automatic).queue_automatic_input_reviews()
    assert service.store.row(first)['status']=='queued'
    row=pump(service,automatic,first,tools)
    assert row['context']['pending']['kind']=='print_review'
    assert not row['context'].get('human_reviews')
    Worker(automatic).queue_automatic_input_reviews()
    assert service.store.row(first)['status']=='waiting_for_input'
    assert service.store.pending_submission(first,row['context']['pending']['pending_input_id']) is None


def test_old_low_resolution_wait_reregisters_original_for_official_backend(setup_service, monkeypatch):
    service, manual, request, original = setup_service
    tools = FixtureTools(monkeypatch)
    run = service.create(ModelTaskRequest.model_validate(request))['run_id']
    before = pump(service, manual, run, tools)
    assert before['context']['prepared']['tool']['data']['method'] != 'backend_official_preprocessing'
    automatic = manual.model_copy(update={'input_review_policy': 'automatic',
        'tools': manual.tools.model_copy(update={'backends': {'triposr': BackendConfig(
            backend='triposr', python=Path('/unused-fixture-python'), execution_root=Path('/unused-fixture-root'))}})})
    Worker(automatic).queue_automatic_input_reviews()
    after = pump(service, automatic, run, tools)['context']
    data = after['prepared']['tool']['data']
    assert data['method'] == 'backend_official_preprocessing'
    artifact = next(a for a in after['artifacts'] if a['artifact_id'] == data['foreground_artifact_id'])
    assert (service.store.root / artifact['relative_path']).read_bytes() == original
    assert tools.calls.count('reconstruct') == 1
    assert not after.get('human_reviews')
