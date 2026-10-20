"""请求、状态和响应的静态一致性校验；不执行状态编排。"""
from uuid import UUID
from typing import Annotated, Literal

from pydantic import Field, StrictInt, model_validator

from .common import (
    ArtifactRecord, CheckResult, ContractModel, Dimensions, ErrorInfo, EvidenceRecord, Id,
    MeshInspection, Orientation, Pending, Positive, PrinterProfile, SCHEMA_VERSION,
    SlicerConfirmation, Status, Text,
)


class ModelTaskRequest(ContractModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    image_asset_id: Id
    height_value: Positive | None = None
    height_unit: Literal["mm", "cm"] | None = None
    scale_source: Literal["user_target", "measured_object"] | None = None
    scale_evidence_id: Id | None = None
    orientation: Orientation = Field(default_factory=Orientation)
    printer_profile_id: Id
    description: Annotated[str, Field(max_length=2000)] = ""

    @model_validator(mode="after")
    def measurement_source(self):
        if self.scale_source == "measured_object" and self.scale_evidence_id is None:
            raise ValueError("实测尺度必须引用测量证据")
        return self

    @property
    def pending_inputs(self):
        result = []
        if self.height_value is None: result.append("height")
        if self.height_unit is None: result.append("height_unit")
        if self.scale_source is None: result.append("scale_source")
        if not self.orientation.confirmed: result.append("orientation")
        return tuple(result)

    @property
    def height_mm(self):
        if self.height_value is None or self.height_unit is None: return None
        return self.height_value * (10 if self.height_unit == "cm" else 1)


class WorkflowState(ContractModel):
    run_id: UUID
    stage: Literal["input", "preprocess", "scale", "reconstruct", "repair", "inspect", "export", "slicer", "complete"]
    status: Status
    pending_input_id: Id | None = None
    pending_input_type: Pending | None = None
    mesh_version: Id | None = None
    repair_round: Annotated[StrictInt, Field(ge=0, le=2)] = 0
    artifacts: list[Id] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    warnings: list[Text] = Field(default_factory=list)
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def status_requirements(self):
        waiting = self.status == "waiting_for_input"
        if waiting != (self.pending_input_id is not None and self.pending_input_type is not None):
            raise ValueError("等待状态与待补输入必须一致")
        if not waiting and (self.pending_input_id is not None or self.pending_input_type is not None):
            raise ValueError("非等待状态不能携带待补输入")
        if self.status == "failed" and self.error is None:
            raise ValueError("失败状态必须给出错误")
        if self.status != "failed" and self.error is not None:
            raise ValueError("错误不得被非失败状态包装")
        if self.status == "succeeded" and (self.stage != "complete" or self.mesh_version is None):
            raise ValueError("成功状态必须处于complete且有关联网格")
        return self


TRANSITIONS = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"waiting_for_input", "succeeded", "failed", "cancel_requested"}),
    "waiting_for_input": frozenset({"queued", "cancelled"}),
    "cancel_requested": frozenset({"cancelled", "failed"}),
    "succeeded": frozenset(), "failed": frozenset(), "cancelled": frozenset(),
}


def allowed_transition(previous: str, following: str) -> bool:
    """仅校验约定是否允许，不推进状态或触发任何操作。"""
    return following in TRANSITIONS.get(previous, ())


class TaskData(ContractModel):
    request: ModelTaskRequest
    state: WorkflowState
    printer_profile: PrinterProfile
    inspection: MeshInspection | None = None
    slicer_confirmation: SlicerConfirmation | None = None


class ModelTaskResponse(ContractModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    request_id: UUID
    task_id: Literal["image_to_3d_print"] = "image_to_3d_print"
    run_id: UUID
    status: Status
    data: TaskData
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    datasets: list[Text] = Field(default_factory=list)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    warnings: list[Text] = Field(default_factory=list)
    events: list[Text] = Field(default_factory=list)
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def coherent_evidence(self):
        state = self.data.state
        if state.run_id != self.run_id or state.status != self.status or state.error != self.error:
            raise ValueError("响应身份、状态与错误必须和内部状态一致")
        artifacts = {a.artifact_id: a for a in self.artifacts}
        if len(artifacts) != len(self.artifacts) or len({e.evidence_id for e in self.evidence}) != len(self.evidence):
            raise ValueError("产物或证据ID不能重复")
        if any(a.run_id != self.run_id for a in self.artifacts):
            raise ValueError("不得引用其他任务的产物")
        if any(aid not in artifacts for aid in state.artifacts):
            raise ValueError("状态引用了不存在的产物")
        for a in self.artifacts:
            if any(parent not in artifacts for parent in a.derived_from):
                raise ValueError("产物来源引用不存在")
        for e in self.evidence:
            if e.run_id != self.run_id or e.artifact_id not in artifacts:
                raise ValueError("证据必须引用本任务产物")
            if e.mesh_version != artifacts[e.artifact_id].mesh_version:
                raise ValueError("证据与产物网格版本不一致")
        profile = self.data.printer_profile
        if self.data.request.printer_profile_id != profile.profile_id:
            raise ValueError("打印配置引用不一致")
        inspection = self.data.inspection
        if inspection is not None:
            for check in inspection.checks:
                if check.status != "not_run":
                    artifact = artifacts.get(check.evidence_artifact_id)
                    if artifact is None or artifact.mesh_version != inspection.mesh_version or artifact.kind != "inspection_report":
                        raise ValueError("检查证据必须对应本版本检查报告")
        if self.status == "succeeded":
            self._require_complete(artifacts)
        return self

    def _require_complete(self, artifacts):
        request, state, profile = self.data.request, self.data.state, self.data.printer_profile
        inspection, slicer = self.data.inspection, self.data.slicer_confirmation
        if request.pending_inputs or profile.build_volume_mm is None:
            raise ValueError("缺尺度、姿态或打印空间不能成功交付")
        if inspection is None or not inspection.ready_for_print or inspection.mesh_version != state.mesh_version:
            raise ValueError("必需检查未齐全、未通过或版本不匹配")
        if slicer is None or slicer.result != "pass" or slicer.mesh_version != state.mesh_version:
            raise ValueError("缺少同版本切片通过证据")
        if slicer.printer_profile_id != profile.profile_id or slicer.slicer_version != profile.slicer_version:
            raise ValueError("切片配置/软件版本不匹配")
        for aid, kind in [(slicer.layer_preview_asset_id, "slicer_preview"), (slicer.confirmation_artifact_id, "slicer_confirmation")]:
            artifact = artifacts.get(aid)
            if artifact is None or artifact.kind != kind or artifact.mesh_version != state.mesh_version:
                raise ValueError("切片确认引用不存在或版本不符")
        candidates = [a for a in artifacts.values() if a.kind == "candidate_stl" and a.mesh_version == state.mesh_version and a.unit == "mm"]
        if not candidates or not any(e.mesh_version == state.mesh_version for e in self.evidence):
            raise ValueError("缺少毫米候选STL或网格证据")
        if not any(e.source_type == "human" and e.artifact_id == slicer.confirmation_artifact_id
                   and e.mesh_version == state.mesh_version for e in self.evidence):
            raise ValueError("最终切片须有对应网格的人工确认来源")
        wall = next(c for c in inspection.checks if c.name == "wall_thickness")
        if type(wall.value) not in {int, float} or wall.value < profile.min_wall_mm or wall.threshold != profile.min_wall_mm:
            raise ValueError("壁厚值与打印配置阈值不一致")
        tolerance = max(.5, request.height_mm * .01)
        if abs(inspection.dimensions_mm[2] - request.height_mm) > tolerance:
            raise ValueError("导出高度不满足尺度约定")
        if any(abs(a-b) > tolerance for a,b in zip(inspection.dimensions_mm, slicer.dimensions_mm)):
            raise ValueError("切片重读尺寸不匹配")
        if any(a>b for a,b in zip(inspection.dimensions_mm, profile.build_volume_mm)):
            raise ValueError("超出打印空间")
