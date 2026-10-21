from uuid import uuid4
from fastapi.testclient import TestClient
from image_to_3d_print.api.app import create_app
from image_to_3d_print.schemas.task import ModelTaskRequest
from .conftest import pump


def test_http_upload_create_query_events_and_cancel(setup_service):
    service, settings, request, payload = setup_service
    client = TestClient(create_app(settings))
    asset = client.post('/api/v1/assets', files={'file': ('user.png', payload, 'image/png')})
    assert asset.status_code == 201
    request['image_asset_id'] = asset.json()['asset_id']
    request.pop('height_value')
    created = client.post('/api/v1/model-tasks', json=request, headers={'Idempotency-Key': 'same'})
    assert created.status_code == 202 and created.json()['status'] == 'queued'
    run = created.json()['run_id']
    assert client.post('/api/v1/model-tasks', json=request, headers={'Idempotency-Key': 'same'}).json()['run_id'] == run
    pump(service, settings, run)
    view = client.get(f'/api/v1/model-tasks/{run}/runtime').json()
    assert view['pending']['kind'] == 'constraints'
    events = client.get(f'/api/v1/model-tasks/{run}/events').json()
    assert events['events'] and all(e['run_id'] == run for e in events['events'])
    assert client.get(f'/api/v1/model-tasks/{run}/events', params={'after': events['next_after']}).json()['events'] == []
    bad = {'submission_id': 'input_1', 'kind': 'constraints', 'pending_input_id': 'wrong', 'height_value': 10.}
    assert client.post(f'/api/v1/model-tasks/{run}/inputs', json=bad).status_code == 409
    assert client.post(f'/api/v1/model-tasks/{run}/cancel').json()['status'] == 'cancelled'
    assert client.post(f'/api/v1/model-tasks/{run}/cancel').json()['status'] == 'cancelled'
    assert client.get(f'/api/v1/model-tasks/{uuid4()}').status_code == 404


def test_file_command_and_credential_boundaries(setup_service, monkeypatch):
    service, settings, request, payload = setup_service
    monkeypatch.setenv('I3D_API_TOKEN', 'test-fixture-api-secret')
    monkeypatch.setenv('I3D_LLM_API_KEY', 'test-fixture-llm-secret')
    client = TestClient(create_app(settings))
    assert client.get('/api/v1/configuration').status_code == 401
    client.headers['Authorization'] = 'Bearer test-fixture-api-secret'
    config = client.get('/api/v1/configuration')
    assert config.status_code == 200 and 'test-fixture' not in config.text
    assert 'root' not in config.json() and 'tools' not in config.json()
    assert client.post('/api/v1/assets', files={'file': ('../../bad.png', payload)}).status_code == 422
    assert client.post('/api/v1/assets', files={'file': ('bad.jpg', payload)}).status_code == 422
    assert client.post('/api/v1/assets', files={'file': ('bad.png', b'not an image')}).status_code == 422
    assert client.post('/api/v1/model-tasks', json={**request, 'command': 'arbitrary'}).status_code == 422
    assert client.post('/api/v1/model-tasks', json={**request, 'image_asset_id': '../../private'}).status_code == 422
    run = client.post('/api/v1/model-tasks', json=request).json()['run_id']
    assert client.get(f'/api/v1/model-tasks/{run}/artifacts/private').status_code == 404
    assert client.post('/api/v1/assets', params={'purpose': 'slicer_preview', 'run_id': run, 'mesh_version': 'm_x'},
        files={'file': ('layers.png', payload)}).status_code == 409


def test_wrapper_backend_and_missing_reference(setup_service):
    service, settings, request, payload = setup_service
    client = TestClient(create_app(settings))
    result = client.post('/api/v1/model-tasks', json={'request': request, 'backend': 'trellis2_candidate'})
    assert result.status_code == 202
    assert service.store.row(result.json()['run_id'])['context']['backend'] == 'trellis2_candidate'
    assert client.post('/api/v1/model-tasks', json={**request, 'printer_profile_id': 'missing'}).status_code == 404
    assert client.get('/api/v1/printer-profiles').json()[0]['profile_id'] == 'demo_v1'


def test_incoherent_measurement_supplement_returns_422(setup_service):
    service, settings, request, _ = setup_service
    request.pop('scale_source')
    client = TestClient(create_app(settings))
    run = client.post('/api/v1/model-tasks', json=request).json()['run_id']
    pump(service, settings, run)
    pending = client.get(f'/api/v1/model-tasks/{run}/runtime').json()['pending']
    result = client.post(f'/api/v1/model-tasks/{run}/inputs', json={'kind': 'constraints', 'submission_id': 'measure',
        'pending_input_id': pending['pending_input_id'], 'scale_source': 'measured_object'})
    assert result.status_code == 422
    assert client.get(f'/api/v1/model-tasks/{run}').json()['status'] == 'waiting_for_input'
