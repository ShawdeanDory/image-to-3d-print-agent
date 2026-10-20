"""公共字段、证据与工具结果，不调用任何模型或外部服务。"""
from typing import Annotated, Literal
from uuid import UUID
from pathlib import PurePosixPath

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictInt, StringConstraints, model_validator

SCHEMA_VERSION = "1.0.0"
Id = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]
NonNegative = Annotated[float, Field(strict=True, ge=0)]
Positive = Annotated[float, Field(strict=True, gt=0)]
Count = Annotated[StrictInt, Field(ge=0)]
Dimensions = Annotated[list[Positive], Field(min_length=3, max_length=3)]
Status = Literal["queued", "running", "waiting_for_input", "cancel_requested", "succeeded", "failed", "cancelled"]
Pending = Literal["height", "height_unit", "scale_source", "orientation", "replacement_image", "repair_confirmation", "slicer_confirmation"]
ErrorCode = Literal["INVALID_IMAGE", "INVALID_ARGUMENT", "MODEL_NOT_CONFIGURED", "TOOL_UNAVAILABLE", "GPU_OUT_OF_MEMORY", "TOOL_TIMEOUT", "MESH_NOT_PRINTABLE", "REPAIR_LIMIT_REACHED", "SLICER_VALIDATION_FAILED", "WORKER_RESTARTED", "REFERENCE_NOT_FOUND", "STATE_CONFLICT", "BUDGET_NOT_CONFIGURED"]


def safe_relative_path(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("产物路径不能包含控制字符")
    if "\\" in value or ":" in value or "%" in value or value.startswith("/"):
        raise ValueError("产物路径必须为项目内POSIX相对路径")
    if any(part in {"", ".", ".."} for part in value.split("/")) or PurePosixPath(value).is_absolute():
        raise ValueError("产物路径不能包含空段、点段或父目录")
    return value


RelativePath = Annotated[Text, AfterValidator(safe_relative_path)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, validate_default=True)


class Orientation(ContractModel):
    up_axis: Literal["x", "y", "z", "-x", "-y", "-z"] | None = None
    confirmed: StrictBool = False

    @model_validator(mode="after")
    def confirmed_axis(self):
        if self.confirmed and self.up_axis is None:
            raise ValueError("确认姿态时必须给出朝上轴")
        return self


class ErrorInfo(ContractModel):
    code: ErrorCode
    message: Text
    details: dict[str, JsonValue] = Field(default_factory=dict)


class PrinterProfile(ContractModel):
    profile_id: Id
    version: Text
    profile_kind: Literal["demo", "verified_device"]
    process: Literal["FDM"]
    material: Literal["PLA"]
    nozzle_mm: Positive
    layer_height_mm: Positive
    min_wall_mm: Positive
    build_volume_mm: Dimensions | None = None
    slicer_version: Text
    supports_policy: Literal["human_review"]


class AssetRecord(ContractModel):
    asset_id: Id
    relative_path: RelativePath
    content_type: Literal["image/png", "image/jpeg"]
    byte_count: Annotated[StrictInt, Field(gt=0, le=10485760)]
    width: Annotated[StrictInt, Field(gt=0, le=4096)]
    height: Annotated[StrictInt, Field(gt=0, le=4096)]


class ArtifactRecord(ContractModel):
    artifact_id: Id
    run_id: UUID
    mesh_version: Id | None = None
    kind: Literal["input_image", "foreground_image", "raw_mesh", "repaired_mesh", "candidate_stl", "quality_report", "inspection_report", "slicer_preview", "slicer_confirmation", "log"]
    relative_path: RelativePath
    created_at: AwareDatetime
    derived_from: list[Id] = Field(default_factory=list)
    unit: Literal["mm", "unitless"] | None = None


class EvidenceRecord(ContractModel):
    evidence_id: Id
    source_type: Literal["input", "tool", "measurement", "human"]
    source_id: Id
    run_id: UUID
    mesh_version: Id | None = None
    artifact_id: Id
    locator: Text
    created_at: AwareDatetime
    summary: Text


class CheckResult(ContractModel):
    name: Id
    status: Literal["pass", "fail", "warn", "not_run"]
    value: JsonValue = None
    threshold: JsonValue = None
    unit: Text | None = None
    tool_version: Text | None = None
    evidence_artifact_id: Id | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def execution_evidence(self):
        if self.status == "not_run":
            if self.value is not None or not self.details.get("reason"):
                raise ValueError("not_run必须保留null值及原因")
        elif self.value is None or self.tool_version is None or self.evidence_artifact_id is None:
            raise ValueError("已执行检查必须有数值、工具版本和证据引用")
        if self.status != "not_run":
            boolean_checks = {"finite_coordinates", "watertight", "normals", "build_volume", "bed_contact"}
            zero_checks = {"boundary_edges", "non_manifold_edges", "non_manifold_vertices", "self_intersection"}
            if self.name in boolean_checks:
                if type(self.value) is not bool or (self.status == "pass" and self.value is not True):
                    raise ValueError("布尔检查的通过状态与实际值矛盾")
            if self.name in zero_checks:
                if type(self.value) is not int or self.value < 0 or (self.status == "pass" and self.value != 0):
                    raise ValueError("缺陷计数必须为非负整数，通过时为0")
        return self


REQUIRED_CHECKS = frozenset({"finite_coordinates", "watertight", "normals", "boundary_edges", "non_manifold_edges", "non_manifold_vertices", "self_intersection", "wall_thickness", "dimensions", "build_volume", "overhang", "bed_contact"})


class MeshInspection(ContractModel):
    mesh_version: Id
    unit: Literal["mm", "unitless"]
    dimensions_mm: Dimensions | None = None
    volume_mm3: NonNegative | None = None
    volume_reason: Text | None = None
    component_count: Count
    watertight: StrictBool
    normals_consistent: StrictBool
    boundary_edge_count: Count
    non_manifold_edge_count: Count
    non_manifold_vertex_count: Count
    checks: list[CheckResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def physical_values(self):
        if self.volume_mm3 is None and self.volume_reason is None:
            raise ValueError("未知体积须说明原因")
        if self.volume_mm3 is not None and (self.unit != "mm" or not self.watertight or not self.normals_consistent):
            raise ValueError("物理体积需要毫米尺度、封闭性与有效方向")
        if len({c.name for c in self.checks}) != len(self.checks):
            raise ValueError("检查名称不能重复")
        return self

    @property
    def ready_for_print(self):
        checks = {c.name: c for c in self.checks}
        return (self.unit == "mm" and self.dimensions_mm is not None and self.watertight
                and self.normals_consistent and self.component_count > 0
                and self.boundary_edge_count == self.non_manifold_edge_count == self.non_manifold_vertex_count == 0
                and REQUIRED_CHECKS <= checks.keys()
                and all(checks[name].status == "pass" or (name == "overhang" and checks[name].status == "warn") for name in REQUIRED_CHECKS))


class SlicerConfirmation(ContractModel):
    pending_input_id: Id
    mesh_version: Id
    result: Literal["pass", "fail"]
    slicer_version: Text
    printer_profile_id: Id
    dimensions_mm: Dimensions
    supports_enabled: StrictBool
    layer_preview_asset_id: Id
    confirmation_artifact_id: Id
    notes: str = ""


class ToolResult(ContractModel):
    run_id: UUID
    tool_name: Literal["preprocess", "reconstruct", "repair", "inspect", "export", "slice"]
    succeeded: StrictBool
    artifact_ids: list[Id] = Field(default_factory=list)
    evidence_ids: list[Id] = Field(default_factory=list)
    data: dict[str, JsonValue] = Field(default_factory=dict)
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def outcome_evidence(self):
        if self.succeeded and (self.error is not None or not (self.artifact_ids or self.evidence_ids)):
            raise ValueError("工具成功须有产物/证据且无错误")
        if not self.succeeded and self.error is None:
            raise ValueError("工具失败必须给出结构化错误")
        return self
