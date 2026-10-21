import json
from uuid import uuid4
from pathlib import Path
import pytest
from image_to_3d_print.schemas.task import ModelTaskRequest, ModelTaskResponse
from image_to_3d_print.tools import ToolFailure
from image_to_3d_print.jobs.store import Store
from image_to_3d_print.jobs.service import TaskService
from image_to_3d_print.geometry.core import MeshStore
from .conftest import FixtureTools, pump, answer, review_image, review_print


def create(service, request): return service.create(ModelTaskRequest.model_validate(request))['run_id']


def to_print(service, settings, request, tools):
    run = create(service, request)
    assert pump(service, settings, run, tools)['context']['pending']['kind'] == 'input_review'
    review_image(service, run)
    row = pump(service, settings, run, tools)
    assert row['context']['pending']['kind'] == 'print_review', row['context'].get('error')
    return run


def test_missing_constraints_persist_and_resume(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    for key in ['height_value', 'height_unit', 'scale_source', 'orientation']: request.pop(key)
    run = create(service, request)
    tools = FixtureTools(monkeypatch)
    row = pump(service, settings, run, tools)
    assert row['status'] == 'waiting_for_input'
    assert row['context']['pending']['details']['missing'] == ['height', 'height_unit', 'scale_source', 'orientation']
    assert tools.calls == []
    service = TaskService(settings)  # 新服务实例从SQLite接续。
    answer(service, run, 'constraints', height_value=1., height_unit='cm', scale_source='user_target',
        orientation={'up_axis': 'z', 'confirmed': True})
    pump(service, settings, run, tools)
    review_image(service, run)
    pump(service, settings, run, tools)
    version = service.store.row(run)['context']['mesh_version']
    review_print(service, run)
    row = pump(service, settings, run, tools)
    assert row['context']['pending']['kind'] == 'slicer'
    assert row['context']['mesh_version'] == version
    assert tools.calls.count('reconstruct') == 1
    assert tools.calls.count('clean') == 1
    assert row['context']['export_data']['independent_readback']


def test_success_requires_slice_preview_and_own_version(setup_service, monkeypatch):
    service, settings, request, payload = setup_service
    tools = FixtureTools(monkeypatch)
    run = to_print(service, settings, request, tools)
    review_print(service, run)
    row = pump(service, settings, run, tools)
    ctx = row['context']
    assert row['status'] == 'waiting_for_input'
    assert ctx['pending']['kind'] == 'slicer'
    assert ctx['latest_report_ids']
    base = dict(result='pass', slicer_version='2.9.6', printer_profile_id='demo_v1', dimensions_mm=[10., 10., 10.],
        supports_enabled=False, model_preview_confirmed=True, bed_confirmed=True, support_reviewed=True)
    with pytest.raises(ToolFailure): answer(service, run, 'slicer', layer_preview_asset_id='missing', **base)
    uploaded = service.upload_slice(run, ctx['mesh_version'], payload, 'layers.png')
    body = answer(service, run, 'slicer', layer_preview_asset_id=uploaded['artifact']['artifact_id'], **base)
    service.submit(run, body)  # 排队阶段重复请求。
    row = pump(service, settings, run, tools)
    assert row['status'] == 'succeeded', row['context'].get('error')
    ModelTaskResponse.model_validate(row['response'])
    assert service.submit(run, body)['status'] == 'succeeded'
    assert tools.calls.count('reconstruct') == 1
    report = next(a for a in reversed(row['context']['artifacts']) if a['kind'] == 'quality_report' and a['relative_path'].endswith('.json'))
    data = json.loads((settings.root / report['relative_path']).read_text(encoding='utf-8'))
    assert data['status'] == 'succeeded' and data['evidence_origin'] == 'test_fixture'
    assert data['llm']['cost'] is None
    assert data['slicer_confirmation']['mesh_version'] == ctx['mesh_version']


def test_structure_confirmation_is_separate_and_versioned(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    tools = FixtureTools(monkeypatch, mesh='open_cube.obj')
    run = to_print(service, settings, request, tools)
    review_print(service, run)
    row = pump(service, settings, run, tools)
    assert row['context']['pending']['kind'] == 'repair_request'
    old = row['context']['mesh_version']
    answer(service, run, 'repair_request', request={'operation': 'fill_small_holes'})
    row = pump(service, settings, run, tools)
    assert row['context']['pending']['kind'] == 'repair_confirmation'
    assert 'apply' not in tools.calls
    proposal = row['context']['pending']['details']['proposal_id']
    body = answer(service, run, 'repair_confirmation', proposal_id=proposal, accepted=True)
    row = pump(service, settings, run, tools)
    assert tools.calls[-3:] == ['confirm', 'apply', 'preview']
    assert row['context']['mesh_version'] != old
    assert row['context']['repair_round'] == 2
    service.submit(run, body)
    assert tools.calls.count('apply') == 1
    with pytest.raises(ToolFailure):
        service.submit(run, {**body, 'submission_id': 'different', 'accepted': False})
    review_print(service, run)
    assert pump(service, settings, run, tools)['context']['pending']['kind'] == 'slicer'


def test_reject_structure_does_not_apply(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    tools = FixtureTools(monkeypatch, mesh='open_cube.obj')
    run = to_print(service, settings, request, tools)
    review_print(service, run)
    pump(service, settings, run, tools)
    answer(service, run, 'repair_request', request={'operation': 'fill_small_holes'})
    row = pump(service, settings, run, tools)
    answer(service, run, 'repair_confirmation', proposal_id=row['context']['proposal']['proposal_id'], accepted=False)
    assert pump(service, settings, run, tools)['status'] == 'failed'
    assert 'apply' not in tools.calls and 'confirm' not in tools.calls


def test_thin_wall_blocks_export(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    tools = FixtureTools(monkeypatch, thin=True)
    run = to_print(service, settings, request, tools)
    review_print(service, run)
    row = pump(service, settings, run, tools)
    assert row['status'] == 'failed' and row['context']['error']['code'] == 'MESH_NOT_PRINTABLE'
    assert 'export' not in tools.calls


def test_two_repair_rounds_stop(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    tools = FixtureTools(monkeypatch, mesh='open_cube.obj', thin=True)
    run = to_print(service, settings, request, tools)
    review_print(service, run)
    pump(service, settings, run, tools)
    answer(service, run, 'repair_request', request={'operation': 'fill_small_holes'})
    row = pump(service, settings, run, tools)
    answer(service, run, 'repair_confirmation', proposal_id=row['context']['proposal']['proposal_id'], accepted=True)
    pump(service, settings, run, tools)
    review_print(service, run)
    row = pump(service, settings, run, tools)
    assert row['context']['error']['code'] == 'REPAIR_LIMIT_REACHED'
    assert tools.calls.count('apply') == 1


def test_create_and_input_idempotency(setup_service):
    service, settings, request, _ = setup_service
    req = ModelTaskRequest.model_validate(request)
    first = service.create(req, 'repeat')
    assert service.create(req, 'repeat')['run_id'] == first['run_id']
    with pytest.raises(ToolFailure): service.create(req.model_copy(update={'height_value': 20.}), 'repeat')
    assert service.cancel(first['run_id'])['status'] == 'cancelled'
    assert service.cancel(first['run_id'])['status'] == 'cancelled'


def test_stale_or_cross_task_input_rejected(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    tools = FixtureTools(monkeypatch)
    run = to_print(service, settings, request, tools)
    pending = service.store.row(run)['context']['pending']
    with pytest.raises(ToolFailure):
        service.submit(run, {'kind': 'print_review', 'submission_id': 's_wrong', 'pending_input_id': pending['pending_input_id'],
            'mesh_version': 'm_wrong', 'preview_artifact_id': pending['details']['preview_artifact_id'], 'bed_confirmed': True})
    another = create(service, request)
    with pytest.raises(ToolFailure):
        service.submit(another, {'kind': 'print_review', 'submission_id': 's_wrong', 'pending_input_id': pending['pending_input_id'],
            'mesh_version': pending['mesh_version'], 'preview_artifact_id': pending['details']['preview_artifact_id'], 'bed_confirmed': True})


def test_missing_llm_is_explicit_and_no_reconstruction(setup_service):
    service, settings, request, _ = setup_service
    request['description'] = '做一个8厘米高的小摆件'
    run = create(service, request)
    row = pump(service, settings, run)
    assert row['context']['error']['code'] == 'MODEL_NOT_CONFIGURED'
    assert row['context']['llm']['availability'] == 'not_configured'
    assert row['context']['tool_calls'] == 0


def test_tool_budget_and_missing_model(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    tools = FixtureTools(monkeypatch)
    limited = settings.model_copy(update={'max_tool_calls': 1})
    run = create(service, request)
    pump(service, limited, run, tools)
    review_image(service, run)
    row = pump(service, limited, run, tools)
    assert row['context']['error']['code'] == 'BUDGET_NOT_CONFIGURED'
    assert tools.calls == ['prepare_image']


def test_checker_unavailable_not_passed(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    tools = FixtureTools(monkeypatch)
    run = to_print(service, settings, request, tools)
    def unavailable(*args, **kwargs): raise ToolFailure('TOOL_UNAVAILABLE', 'TEST_FIXTURE missing checker')
    monkeypatch.setattr('image_to_3d_print.inspection.service.blender_call', unavailable)
    review_print(service, run)
    row = pump(service, settings, run, tools)
    assert row['context']['error']['code'] == 'TOOL_UNAVAILABLE'
    assert any(c['status'] == 'not_run' for c in row['context']['inspection']['checks'])
    assert 'export' not in tools.calls


def test_llm_suggestions_need_explicit_human_constraints(setup_service, monkeypatch):
    from image_to_3d_print.runtime_contracts import ParsedRequirements
    class FixtureLLM:
        def call(self, ctx, store, purpose, evidence):
            return ParsedRequirements(height_value=8., height_unit='cm', scale_source='user_target',
                up_axis='z', questions=['TEST_FIXTURE：请确认方向'])
    service, settings, request, _ = setup_service
    request = {'image_asset_id': request['image_asset_id'], 'printer_profile_id': request['printer_profile_id'],
        'description': '测试描述：8厘米高'}
    tools = FixtureTools(monkeypatch)
    run = create(service, request)
    row = pump(service, settings, run, tools, FixtureLLM())
    assert tools.calls == []
    assert row['context']['request']['height_value'] is None
    assert not row['context']['request']['orientation']['confirmed']
    answer(service, run, 'constraints', accept_suggestions=True)
    row = pump(service, settings, run, tools, FixtureLLM())
    assert row['context']['request']['height_value'] == 8.
    assert row['context']['pending']['details']['missing'] == ['orientation']
    assert tools.calls == []
    answer(service, run, 'constraints', orientation={'up_axis': 'z', 'confirmed': True})
    assert pump(service, settings, run, tools, FixtureLLM())['context']['pending']['kind'] == 'input_review'


def test_slicer_failure_keeps_mesh_and_stops(setup_service, monkeypatch):
    service, settings, request, payload = setup_service
    tools = FixtureTools(monkeypatch)
    run = to_print(service, settings, request, tools)
    review_print(service, run)
    ctx = pump(service, settings, run, tools)['context']
    uploaded = service.upload_slice(run, ctx['mesh_version'], payload, 'layers.png')
    answer(service, run, 'slicer', result='fail', slicer_version='2.9.6', printer_profile_id='demo_v1',
        dimensions_mm=[10., 10., 10.], supports_enabled=False, model_preview_confirmed=True,
        bed_confirmed=False, support_reviewed=True, layer_preview_asset_id=uploaded['artifact']['artifact_id'])
    row = pump(service, settings, run, tools)
    assert row['context']['error']['code'] == 'SLICER_VALIDATION_FAILED'
    assert row['context']['mesh_version'] == ctx['mesh_version']


def test_missing_real_reconstruction_configuration(setup_service):
    service, settings, request, _ = setup_service
    run = create(service, request)
    pump(service, settings, run)
    review_image(service, run)
    row = pump(service, settings, run)
    assert row['context']['error']['code'] == 'MODEL_NOT_CONFIGURED'
    assert row['context']['mesh_version'] is None
