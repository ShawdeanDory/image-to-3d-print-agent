import json
import httpx
import pytest
from image_to_3d_print.workflow.llm import LanguageModel
from image_to_3d_print.jobs.config import LLMConfig
from image_to_3d_print.schemas.task import ModelTaskRequest
from image_to_3d_print.tools import ToolFailure


def context(service, request):
    run = service.create(ModelTaskRequest.model_validate(request))['run_id']
    return service.store.row(run)['context']


def mock_http(monkeypatch, reply):
    original = httpx.Client
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        assert request.headers['Authorization'] == 'Bearer fixture-key'
        return httpx.Response(200, json=reply)
    monkeypatch.setattr('image_to_3d_print.workflow.llm.httpx.Client',
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setenv('I3D_LLM_API_KEY', 'fixture-key')
    return seen


def valid_reply(content=None):
    return {'usage': {'prompt_tokens': 100, 'completion_tokens': 30}, 'choices': [{'message': {'content': json.dumps(
        content or {'height_value': 8., 'height_unit': 'cm', 'scale_source': 'user_target', 'up_axis': 'z',
            'questions': ['请确认方向'], 'explanation': '测试替身输出'}, ensure_ascii=False)}}]}


def test_real_adapter_with_marked_mock_transport_and_budgets(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    seen = mock_http(monkeypatch, valid_reply())
    model = LanguageModel(LLMConfig(base_url='https://fixture.invalid/v1', model='TEST_FIXTURE'))
    ctx = context(service, request)
    for _ in range(4):
        result = model.call(ctx, service.store, 'parse', {'text': '8厘米高'})
        assert result.height_value == 8. and not hasattr(result, 'confirmed')
    assert ctx['llm']['calls'] == 4 and ctx['llm']['input_tokens'] == 400
    assert ctx['llm']['output_tokens'] == 120 and ctx['llm']['cost'] is None
    assert len(seen) == 4 and all(s['max_tokens'] <= 2048 for s in seen)
    with pytest.raises(ToolFailure): model.call(ctx, service.store, 'parse', {'text': 'more'})
    assert len(seen) == 4


def test_reject_llm_tool_and_confirmation_fields(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    seen = mock_http(monkeypatch, valid_reply({'confirmed': True, 'command': 'run shell'}))
    ctx = context(service, request)
    with pytest.raises(ToolFailure) as error:
        LanguageModel(LLMConfig(base_url='https://fixture.invalid', model='TEST_FIXTURE')).call(ctx, service.store, 'parse', {})
    assert error.value.code == 'TOOL_UNAVAILABLE'
    assert len(seen) == 1


def test_missing_usage_blocks_future_calls(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    reply = valid_reply()
    reply.pop('usage')
    seen = mock_http(monkeypatch, reply)
    ctx = context(service, request)
    model = LanguageModel(LLMConfig(base_url='https://fixture.invalid', model='TEST_FIXTURE'))
    with pytest.raises(ToolFailure): model.call(ctx, service.store, 'parse', {})
    assert not ctx['llm']['usage_complete'] and ctx['llm']['reserved_tokens'] > 0
    with pytest.raises(ToolFailure): model.call(ctx, service.store, 'parse', {})
    assert len(seen) == 1


def test_prompt_budget_prevents_request(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    seen = mock_http(monkeypatch, valid_reply())
    ctx = context(service, request)
    with pytest.raises(ToolFailure):
        LanguageModel(LLMConfig(base_url='https://fixture.invalid', model='TEST_FIXTURE')).call(ctx, service.store, 'parse', {'text': '长' * 5000})
    assert seen == [] and ctx['llm']['calls'] == 0


def test_timeout_is_not_retried_and_usage_unknown(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    original = httpx.Client
    calls = []
    def timeout(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout('TEST_FIXTURE timeout')
    monkeypatch.setenv('I3D_LLM_API_KEY', 'fixture-key')
    monkeypatch.setattr('image_to_3d_print.workflow.llm.httpx.Client',
        lambda **kwargs: original(transport=httpx.MockTransport(timeout), **kwargs))
    ctx = context(service, request)
    with pytest.raises(ToolFailure) as error:
        LanguageModel(LLMConfig(base_url='https://fixture.invalid', model='TEST_FIXTURE')).call(ctx, service.store, 'parse', {})
    assert error.value.code == 'TOOL_TIMEOUT' and len(calls) == 1
    assert ctx['llm']['records'][0]['input_tokens'] is None
    assert not ctx['llm']['usage_complete']


def test_graph_explanation_uses_evidence_and_not_final_status(setup_service, monkeypatch):
    from .conftest import FixtureTools, pump, review_image, review_print
    service, settings, request, _ = setup_service
    seen = mock_http(monkeypatch, valid_reply({'questions': [], 'explanation': 'TEST_FIXTURE基于检查记录的说明'}))
    configured = settings.model_copy(update={'llm': LLMConfig(base_url='https://fixture.invalid', model='TEST_FIXTURE')})
    tools = FixtureTools(monkeypatch)
    run = service.create(ModelTaskRequest.model_validate(request))['run_id']
    pump(service, configured, run, tools)
    review_image(service, run)
    pump(service, configured, run, tools)
    review_print(service, run)
    row = pump(service, configured, run, tools)
    assert row['status'] == 'waiting_for_input' and row['context']['pending']['kind'] == 'slicer'
    assert row['context']['explanation'].startswith('TEST_FIXTURE')
    assert len(seen) == 1 and row['context']['llm']['calls'] == 1
    assert 'wall_thickness' in seen[0]['messages'][1]['content']
