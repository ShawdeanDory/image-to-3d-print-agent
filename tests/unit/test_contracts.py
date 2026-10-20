"""输入、状态、检查和安全边界的契约回归。"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from image_to_3d_print.schemas import (
    ArtifactRecord, CheckResult, ErrorInfo, EvidenceRecord, ModelTaskRequest,
    PrinterProfile, ToolResult, WorkflowState, allowed_transition,
    resolve_artifact_path, validate_request_references,
)

RUN = UUID("00000000-0000-4000-8000-000000000001")


def request(**changes):
    data = dict(image_asset_id="asset_cube", height_value=80, height_unit="mm",
                scale_source="user_target", orientation={"up_axis": "z", "confirmed": True},
                printer_profile_id="demo_v1")
    data.update(changes)
    return ModelTaskRequest.model_validate(data)


def test_scale_and_missing_inputs():
    assert request(height_value=8, height_unit="cm").height_mm == 80
    pending = request(height_value=None, height_unit=None, scale_source=None, orientation={})
    assert set(pending.pending_inputs) == {"height", "height_unit", "scale_source", "orientation"}
    assert pending.height_mm is None


@pytest.mark.parametrize("height", [-1, 0, float("nan"), float("inf"), True, "80"])
def test_bad_height_rejected(height):
    with pytest.raises(ValidationError):
        request(height_value=height)


@pytest.mark.parametrize("changes", [
    {"height_unit": "inch"}, {"image_asset_id": "../../secret"},
    {"image_asset_id": r"C:\secret"}, {"shell": "whoami"},
    {"scale_source": "measured_object", "scale_evidence_id": None},
    {"orientation": {"confirmed": True}},
])
def test_request_boundaries(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_unknown_asset_and_profile_rejected():
    profile = PrinterProfile(profile_id="demo_v1", version="1.0.0", profile_kind="demo",
        process="FDM", material="PLA", nozzle_mm=.4, layer_height_mm=.2, min_wall_mm=1.2,
        build_volume_mm=[220, 220, 250], slicer_version="2.9.6", supports_policy="human_review")
    validate_request_references(request(), {"asset_cube"}, {"demo_v1": profile}, set())
    for assets, profiles in [(set(), {"demo_v1": profile}), ({"asset_cube"}, {})]:
        with pytest.raises(ValueError):
            validate_request_references(request(), assets, profiles, set())
    with pytest.raises(ValueError):
        validate_request_references(request(scale_source="measured_object", scale_evidence_id="measure_1"),
                                    {"asset_cube"}, {"demo_v1": profile}, set())


def test_not_run_requires_unknown_value_and_reason():
    check = CheckResult(name="self_intersection", status="not_run", value=None,
                        threshold=0, unit="faces", details={"reason": "工具未执行"})
    assert check.value is None
    for changes in [{"value": 0}, {"details": {}}]:
        with pytest.raises(ValidationError):
            CheckResult.model_validate(check.model_dump() | changes)
    with pytest.raises(ValidationError):
        CheckResult(name="watertight", status="pass", value=True, unit="bool", details={})


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "C:/Windows/x", r"a\b", "a\b", "a/../b", "a//b", "%2e%2e/x"])
def test_unsafe_artifact_paths(path):
    with pytest.raises(ValidationError):
        ArtifactRecord(artifact_id="artifact_1", run_id=RUN, kind="log", relative_path=path,
                       created_at=datetime.now(timezone.utc))


def test_resolver_requires_file_inside_root(tmp_path):
    (tmp_path / "logs").mkdir(); (tmp_path / "logs/out.txt").write_text("ok")
    assert resolve_artifact_path(tmp_path, "logs/out.txt").is_file()
    with pytest.raises(ValueError): resolve_artifact_path(tmp_path, "logs/missing.txt")
    with pytest.raises(ValueError): resolve_artifact_path(tmp_path, "../outside")


def test_timezone_and_tool_outcome():
    with pytest.raises(ValidationError):
        EvidenceRecord(evidence_id="e1", source_type="tool", source_id="t1", run_id=RUN,
                       artifact_id="a1", locator="checks", created_at=datetime(2026, 10, 19), summary="未带时区")
    with pytest.raises(ValidationError):
        ToolResult(run_id=RUN, tool_name="reconstruct", succeeded=True)
    with pytest.raises(ValidationError):
        ToolResult(run_id=RUN, tool_name="reconstruct", succeeded=False)
    tool = ToolResult(run_id=RUN, tool_name="reconstruct", succeeded=False,
                      error=ErrorInfo(code="TOOL_UNAVAILABLE", message="未安装"))
    assert not tool.succeeded


def test_state_and_transition_contract():
    with pytest.raises(ValidationError): WorkflowState(run_id=RUN, stage="scale", status="waiting_for_input")
    with pytest.raises(ValidationError): WorkflowState(run_id=RUN, stage="repair", status="running", repair_round=3)
    with pytest.raises(ValidationError): WorkflowState(run_id=RUN, stage="reconstruct", status="failed")
    assert allowed_transition("queued", "running")
    assert allowed_transition("waiting_for_input", "queued")
    assert not allowed_transition("succeeded", "running")
    assert not allowed_transition("queued", "succeeded")
