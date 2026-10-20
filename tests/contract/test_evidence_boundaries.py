"""补充真实可达的证据矛盾、保留集与引用边界。"""
import json
from pathlib import Path
from uuid import UUID
import pytest
from pydantic import ValidationError
from image_to_3d_print.schemas import (AssetRecord, BudgetPlan, CheckResult, ExperimentRecord,
    ModelTaskResponse, http_status_for_boundary_error, validate_experiment_references,
    validate_response_references)
ROOT=Path(__file__).resolve().parents[2]
def load(name):return json.loads((ROOT/"fixtures/p1/contracts"/name).read_text(encoding="utf-8"))

@pytest.mark.parametrize("name,value",[("watertight",False),("normals",False),("self_intersection",3),("boundary_edges",1)])
def test_pass_check_cannot_contradict_value(name,value):
    with pytest.raises(ValidationError):
        CheckResult(name=name,status="pass",value=value,tool_version="fixture",unit="count",evidence_artifact_id="report_1")

def test_print_success_needs_human_slicer_evidence():
    payload=load("response_success.json")
    payload["evidence"]=[e for e in payload["evidence"] if e["source_type"]!="human"]
    with pytest.raises(ValidationError):ModelTaskResponse.model_validate(payload)

def test_holdout_execution_requires_frozen_release():
    payload=load("experiment_success.json");payload["split"]="holdout"
    with pytest.raises(ValidationError):ExperimentRecord.model_validate(payload)

def test_boundary_http_mapping_is_separate_from_tool_failure():
    assert http_status_for_boundary_error("INVALID_ARGUMENT")==422
    assert http_status_for_boundary_error("REFERENCE_NOT_FOUND")==404
    assert http_status_for_boundary_error("STATE_CONFLICT")==409
    with pytest.raises(ValueError):http_status_for_boundary_error("TOOL_TIMEOUT")

def test_actual_artifact_paths_and_cross_experiment_references(tmp_path):
    response=ModelTaskResponse.model_validate(load("response_success.json"))
    for artifact in response.artifacts:
        path=tmp_path/artifact.relative_path;path.parent.mkdir(parents=True,exist_ok=True);path.write_text("offline reference fixture")
    assert validate_response_references(response,tmp_path).run_id==response.run_id
    budget=BudgetPlan(budget_id="fixture_budget",state="confirmed",preparation_timeout_s=30,inference_timeout_s=10,max_retries=0,cost_limit_cny=0,confirmed_by="test_author")
    record=ExperimentRecord.model_validate(load("experiment_success.json"))
    with pytest.raises(ValueError):validate_experiment_references(record,set(),set(),budget)
    assert validate_experiment_references(record,{"artifact_fixture"},{"evidence_fixture"},budget)==record

def test_valid_asset_registry_and_geometry_manifest():
    assets=json.loads((ROOT/"fixtures/p1/assets.json").read_text(encoding="utf-8"))
    assert all(AssetRecord.model_validate(asset) for asset in assets)


def test_invalid_upload_does_not_alias_valid_registered_asset():
    assets={a["asset_id"]:a for a in json.loads((ROOT/"fixtures/p1/assets.json").read_text(encoding="utf-8"))}
    cases=json.loads((ROOT/"evals/dataset_v1.json").read_text(encoding="utf-8"))["cases"]
    for case in cases:
        aid=case["request"]["image_asset_id"]
        if case["image_should_decode"]:
            assert assets[aid]["relative_path"]==case["asset_path"]
        else:
            assert aid not in assets
