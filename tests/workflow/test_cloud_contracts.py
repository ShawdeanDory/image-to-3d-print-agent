"""云端固定验证的来源及供应商参数，均为离线回归。"""
import json
from image_to_3d_print.jobs.config import Settings, LLMConfig
from image_to_3d_print.jobs.service import TaskService
from image_to_3d_print.schemas.task import ModelTaskRequest
from image_to_3d_print.workflow.llm import LanguageModel
from .conftest import FixtureTools, pump, review_image
from .test_llm import context, mock_http, valid_reply


def test_fixture_confirmation_is_not_human_evidence(setup_service, monkeypatch):
    old, settings, request, _ = setup_service
    settings=Settings.model_validate(settings.model_dump() | {'confirmation_origin':'test_fixture'})
    service=TaskService(settings);tools=FixtureTools(monkeypatch)
    run=service.create(ModelTaskRequest.model_validate(request))['run_id']
    pump(service, settings, run, tools);review_image(service, run)
    row=pump(service, settings, run, tools);ctx=row['context']
    assert ctx['input_review']['origin']=='test_fixture'
    assert ctx['evidence_origin']=='test_fixture'
    assert all(e['source_type']!='human' for e in ctx['evidence'])
    assert ctx['human_reviews'][0]['origin']=='test_fixture'


def test_deepseek_thinking_option_and_json_example(setup_service, monkeypatch):
    service, settings, request, _ = setup_service
    seen=mock_http(monkeypatch, valid_reply())
    cfg=LLMConfig(base_url='https://fixture.invalid',model='TEST_FIXTURE',thinking_mode='disabled')
    LanguageModel(cfg).call(context(service,request),service.store,'parse',{'text':'8厘米高'})
    assert seen[0]['thinking']=={'type':'disabled'}
    system=seen[0]['messages'][0]['content']
    assert '"height_value":null' in system and '"questions":[]' in system
    from image_to_3d_print.runtime_contracts import ParsedRequirements
    example=json.JSONDecoder().raw_decode(system.split('JSON示例：',1)[1])[0]
    ParsedRequirements.model_validate(example)
