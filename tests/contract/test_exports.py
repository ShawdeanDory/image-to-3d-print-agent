"""检查导出文件与可执行公共契约一致，避免文档快照漂移。"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/p1" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exported_schema_matches_public_models():
    exporter = load_script("export_schemas")
    actual = (ROOT / "schemas/contracts-v1.schema.json").read_text(encoding="utf-8")
    assert actual == exporter.serialized_schema()
    document = json.loads(actual)
    assert document["x-contract-version"] == "1.0.0"
    assert set(document["x-public-models"]) <= document["$defs"].keys()


def test_prepared_data_has_no_claimed_model_results():
    report = load_script("check_prepared_data").check_prepared_data()
    assert report["all_case_results"] == "not_run"
    assert report["holdout_model_execution"] == "not_run"
    assert report["p2_budget_blocked"]


def test_comparison_protocol_uses_evaluation_and_keeps_holdout_closed():
    protocol = json.loads((ROOT / "evals/protocol_v1.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "evals/dataset_v1.json").read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in manifest["cases"]}
    assert protocol["dataset_version"] == manifest["dataset_version"]
    for category, key in [("normal", "paired_normal_cases"), ("boundary", "boundary_cases")]:
        expected = {case_id for case_id, case in cases.items()
                    if case["split"] == "evaluation" and case["category"] == category}
        assert set(protocol[key]) == expected
    assert {item["type"] for item in protocol["experiments"]} == {
        "official_inference", "model_comparison", "repair_comparison", "workflow_comparison"}
    assert all(item["status"] == "not_run" for item in protocol["experiments"])
    assert protocol["execution_allowed"] is False
