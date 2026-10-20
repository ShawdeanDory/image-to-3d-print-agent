"""实验、成功证据和固定数据的跨字段校验。"""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from image_to_3d_print.schemas import (
    AssetRecord, BudgetPlan, DatasetManifest, ExperimentRecord, MetricValue, ModelTaskResponse,
    validate_dataset_files, validate_response_references,
)

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    return json.loads((ROOT / "fixtures/p1/contracts" / name).read_text(encoding="utf-8"))


def test_valid_contract_snapshots_roundtrip():
    for name, model in [("request_pending.json", __import__("image_to_3d_print.schemas", fromlist=["ModelTaskRequest"]).ModelTaskRequest),
                        ("response_success.json", ModelTaskResponse), ("experiment_success.json", ExperimentRecord)]:
        value = model.model_validate(load(name))
        assert model.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("mutation", ["missing_scale", "missing_checks", "unknown_space", "missing_slicer", "wrong_mesh", "missing_artifact", "cross_run"])
def test_success_requires_matching_evidence(mutation):
    payload = load("response_success.json")
    if mutation == "missing_scale": payload["data"]["request"]["height_value"] = None
    elif mutation == "missing_checks": payload["data"]["inspection"]["checks"] = []
    elif mutation == "unknown_space": payload["data"]["printer_profile"]["build_volume_mm"] = None
    elif mutation == "missing_slicer": payload["data"]["slicer_confirmation"] = None
    elif mutation == "wrong_mesh": payload["data"]["slicer_confirmation"]["mesh_version"] = "other_mesh"
    elif mutation == "missing_artifact": payload["artifacts"] = payload["artifacts"][:-1]
    else: payload["artifacts"][0]["run_id"] = "00000000-0000-4000-8000-000000000099"
    with pytest.raises(ValidationError): ModelTaskResponse.model_validate(payload)


@pytest.mark.parametrize("field,value", [("upstream_commit", None), ("weights_revision", "main"),
    ("exit_code", 7), ("parameters", {}), ("evidence_ids", []), ("seed", -1), ("budget_ref", None)])
def test_experiment_incomplete_or_failed_not_success(field, value):
    payload = load("experiment_success.json"); payload[field] = value
    with pytest.raises(ValidationError): ExperimentRecord.model_validate(payload)


def test_unknown_metrics_and_budget_gate():
    assert MetricValue(name="inference_seconds", status="unknown", unit="s", reason="未执行").value is None
    with pytest.raises(ValidationError):
        MetricValue(name="inference_seconds", status="unknown", value=0, unit="s", reason="未执行")
    with pytest.raises(ValidationError):
        MetricValue(name="inference_seconds", status="measured", value=-1, unit="s")
    draft = BudgetPlan.model_validate(json.loads((ROOT / "evals/budgets/p2a_draft.json").read_text(encoding="utf-8")))
    with pytest.raises(ValueError): draft.require_ready()
    assert MetricValue(name="defects", status="measured", value=0, unit="count").value == 0


def test_dataset_is_complete_and_object_disjoint():
    payload = json.loads((ROOT / "evals/dataset_v1.json").read_text(encoding="utf-8"))
    manifest = DatasetManifest.model_validate(payload)
    assert len(manifest.cases) == 30
    assets = [AssetRecord.model_validate(a) for a in json.loads((ROOT / "fixtures/p1/assets.json").read_text(encoding="utf-8"))]
    validate_dataset_files(manifest, ROOT, assets)
    for split in ["development", "evaluation", "holdout"]:
        cases = [c for c in manifest.cases if c.split == split]
        assert len(cases) == 10
        assert sum(c.category == "normal" for c in cases) == 6
    payload["cases"][10]["object_group"] = payload["cases"][0]["object_group"]
    with pytest.raises(ValidationError): DatasetManifest.model_validate(payload)


def test_artifact_references_cannot_be_missing_files(tmp_path):
    response = ModelTaskResponse.model_validate(load("response_success.json"))
    with pytest.raises(ValueError): validate_response_references(response, tmp_path)
