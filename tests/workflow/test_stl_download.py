"""模型/Blender仅为fixture；真实SQLite、交付GLB和STL转换读回。"""
import hashlib
import io
from uuid import uuid4

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from image_to_3d_print.api.app import create_app
from image_to_3d_print.runtime_contracts import CreateTask
from image_to_3d_print.tools import digest
from .conftest import pump
from .test_automatic_generation import automatic
from .test_repaired_delivery import TexturedFixture


def completed(setup_service, monkeypatch, thin=False):
    service, settings, request = automatic(setup_service)
    tools = TexturedFixture(monkeypatch, thin=thin)
    run = service.create(CreateTask(request=request))['run_id']
    row = pump(service, settings, run, tools)
    assert row['status'] == 'succeeded'
    version = row['response']['delivery']['mesh_version']
    return service, settings, tools, run, version


@pytest.mark.parametrize('thin', [False, True])
def test_same_version_stl_and_no_snapshot_or_model_changes(setup_service, monkeypatch, thin):
    service, settings, tools, run, version = completed(setup_service, monkeypatch, thin)
    client = TestClient(create_app(settings))
    before = service.store.row(run)
    result = client.get(f'/api/v1/model-tasks/{run}/delivery.stl', params={'mesh_version': version})
    assert result.status_code == 200, result.text
    assert result.headers['content-type'] == 'model/stl'
    assert result.headers['x-mesh-version'] == version
    assert result.headers['x-mesh-unit'] == 'mm'
    assert result.headers['x-print-certified'] == 'false'
    assert result.headers['x-print-check'] == ('failed' if thin else 'passed')
    mesh = trimesh.load(io.BytesIO(result.content), file_type='stl', force='mesh')
    np.testing.assert_allclose(mesh.extents, [10, 10, 10], atol=.001)
    assert len(mesh.faces) == 12
    again = client.get(f'/api/v1/model-tasks/{run}/delivery.stl', params={'mesh_version': version})
    assert hashlib.sha256(again.content).digest() == hashlib.sha256(result.content).digest()
    assert service.store.row(run) == before
    assert digest(tools.original) == tools.original_sha
    assert tools.calls.count('reconstruct') == 1


def test_stl_rejects_stale_version_unknown_task_and_missing_file(setup_service, monkeypatch):
    service, settings, tools, run, version = completed(setup_service, monkeypatch)
    client = TestClient(create_app(settings))
    url = f'/api/v1/model-tasks/{run}/delivery.stl'
    assert client.get(url, params={'mesh_version': 'm_' + 'a' * 24}).status_code == 409
    assert client.get(url, params={'mesh_version': '../../private'}).status_code == 422
    assert client.get(f'/api/v1/model-tasks/{uuid4()}/delivery.stl', params={'mesh_version': version}).status_code == 404
    artifact = next(a for a in service.store.row(run)['response']['artifacts']
                    if a['artifact_id'] == service.store.row(run)['response']['delivery']['artifact_id'])
    (settings.root / artifact['relative_path']).unlink()
    assert client.get(url, params={'mesh_version': version}).status_code == 404


def test_stl_requires_authentication(setup_service, monkeypatch):
    service, settings, tools, run, version = completed(setup_service, monkeypatch)
    monkeypatch.setenv('I3D_API_TOKEN', 'test-fixture-api-secret')
    client = TestClient(create_app(settings))
    url = f'/api/v1/model-tasks/{run}/delivery.stl'
    assert client.get(url, params={'mesh_version': version}).status_code == 401
    result = client.get(url, params={'mesh_version': version}, headers={'Authorization': 'Bearer test-fixture-api-secret'})
    assert result.status_code == 200


def test_stl_rejects_pending_and_original_snapshots(setup_service, monkeypatch):
    service, settings, tools, run, version = completed(setup_service, monkeypatch)
    client = TestClient(create_app(settings))
    # 待处理请求不能下载；历史原件完成后也不能借检查副本隐式定标。
    from image_to_3d_print.workflow.state import save_context
    ctx = service.store.row(run)['context']
    ctx['delivery_policy'] = 'original-glb-v1'
    ctx['status'] = 'queued'
    ctx['delivery'] = None
    save_context(service.store, ctx)
    assert client.get(f'/api/v1/model-tasks/{run}/delivery.stl', params={'mesh_version': version}).status_code == 409
    row = pump(service, settings, run, tools)
    assert row['response']['schema_version'] == 'original-glb-v1'
    original_version = row['response']['delivery']['mesh_version']
    assert client.get(f'/api/v1/model-tasks/{run}/delivery.stl', params={'mesh_version': original_version}).status_code == 409
