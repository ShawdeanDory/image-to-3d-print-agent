"""静态检查P1清单、文件和契约样例；不执行模型、指标或保留集评估。"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from image_to_3d_print.schemas import (
    AssetRecord, BudgetPlan, DatasetManifest, ExperimentRecord, ModelTaskRequest,
    ModelTaskResponse, PrinterProfile, resolve_artifact_path,
    validate_dataset_files, validate_request_references, validate_response_references,
)


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def check_prepared_data():
    manifest = DatasetManifest.model_validate(load("evals/dataset_v1.json"))
    assets = [AssetRecord.model_validate(item) for item in load("fixtures/p1/assets.json")]
    validate_dataset_files(manifest, ROOT, assets)
    profiles = [PrinterProfile.model_validate(load("fixtures/p1/" + name)) for name in (
        "printer_profile.json", "printer_profile_unknown.json")]
    for case in manifest.cases:
        # 无效上传尚未创建asset，不把计划请求当作已注册请求。
        if case.image_should_decode and case.request_should_validate:
            validate_request_references(ModelTaskRequest.model_validate(case.request),
                {asset.asset_id for asset in assets}, {p.profile_id for p in profiles}, set())
    response = ModelTaskResponse.model_validate(load("fixtures/p1/contracts/response_success.json"))
    validate_response_references(response, ROOT)
    ExperimentRecord.model_validate(load("fixtures/p1/contracts/experiment_success.json"))
    ModelTaskRequest.model_validate(load("fixtures/p1/contracts/request_pending.json"))
    geometry = load("fixtures/p1/geometry/manifest.json")
    for item in geometry["fixtures"]:
        resolve_artifact_path(ROOT / "fixtures/p1/geometry", item["file"])
    budget = BudgetPlan.model_validate(load("evals/budgets/p2a_draft.json"))
    try:
        budget.require_ready()
    except ValueError:
        blocked = True
    else:
        blocked = False
    if not blocked:
        raise ValueError("本轮P2-A预算应保持未确认，不能自动放行")
    return {
        "check_kind": "static_preparation_only",
        "schema_version": "1.0.0", "dataset_version": manifest.dataset_version,
        "cases": len(manifest.cases),
        "splits": dict(Counter(case.split for case in manifest.cases)),
        "categories": dict(Counter(case.category for case in manifest.cases)),
        "registered_images": len(assets), "geometry_files": len(geometry["fixtures"]),
        "all_case_results": "not_run", "holdout_model_execution": "not_run",
        "contract_examples": "validated_synthetic_fixtures",
        "gpu_used": False, "model_installed_or_executed": False,
        "p2_budget_blocked": blocked,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="可选的本地检查摘要文件")
    args = parser.parse_args()
    report = check_prepared_data()
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")


if __name__ == "__main__":
    main()
