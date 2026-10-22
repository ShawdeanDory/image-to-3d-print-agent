"""运行时v1扩展；公共1.0.0模型与状态保持兼容。"""
from typing import Annotated, Literal, Union
from uuid import UUID
from pydantic import Field, StrictBool, StrictInt, model_validator
from .schemas.common import ContractModel, Id, Text, Orientation, Positive, Dimensions, Status
from .schemas.task import ModelTaskRequest, ModelTaskResponse, WorkflowState
from .geometry.structure import StructureRequest
from .export_options import ExportTargetFaces, TextureSize

Backend = Literal['triposr', 'trellis2_candidate']
WorkflowStage = WorkflowState.model_fields['stage'].annotation


class CreateTask(ContractModel):
    request: ModelTaskRequest
    backend: Backend | None = None
    reconstruction_profile: Literal['official','course_fast'] | None = None
    export_target_faces: ExportTargetFaces | None = None
    texture_size: TextureSize | None = None

    @model_validator(mode='after')
    def profile_backend(self):
        if self.reconstruction_profile=='course_fast' and self.backend!='trellis2_candidate':
            raise ValueError('课程快速模式必须明确选择TRELLIS.2')
        return self


class InputBase(ContractModel):
    submission_id: Id
    pending_input_id: Id
    mesh_version: Id | None = None


class ConstraintsInput(InputBase):
    kind: Literal['constraints']
    height_value: Positive | None = None
    height_unit: Literal['mm', 'cm'] | None = None
    scale_source: Literal['user_target', 'measured_object'] | None = None
    scale_evidence_id: Id | None = None
    orientation: Orientation | None = None
    accept_suggestions: StrictBool = False


class ImageReviewInput(InputBase):
    kind: Literal['input_review']
    foreground_artifact_id: Id
    decision: Literal['accepted', 'replace_image', 'uncertain']
    complete_subject: StrictBool
    simple_nonfunctional_ornament: StrictBool
    foreground_correct: StrictBool


class PrintReviewInput(InputBase):
    kind: Literal['print_review']
    preview_artifact_id: Id
    bed_confirmed: StrictBool
    component_count: Annotated[StrictInt, Field(ge=1)] | None = None
    components_confirmed: StrictBool = False


class RepairRequestInput(InputBase):
    kind: Literal['repair_request']
    request: StructureRequest | None = None
    stop: StrictBool = False


class RepairConfirmInput(InputBase):
    kind: Literal['repair_confirmation']
    proposal_id: Id
    accepted: StrictBool


class SlicerInput(InputBase):
    kind: Literal['slicer']
    mesh_version: Id
    result: Literal['pass', 'fail']
    slicer_version: Text
    printer_profile_id: Id
    dimensions_mm: Dimensions
    supports_enabled: StrictBool
    layer_preview_asset_id: Id
    model_preview_confirmed: StrictBool
    bed_confirmed: StrictBool
    support_reviewed: StrictBool
    notes: Annotated[str, Field(max_length=2000)] = ''


Submission = Annotated[Union[ConstraintsInput, ImageReviewInput, PrintReviewInput,
    RepairRequestInput, RepairConfirmInput, SlicerInput], Field(discriminator='kind')]


class RuntimeEvent(ContractModel):
    event_id: StrictInt
    run_id: UUID
    kind: Id
    stage: WorkflowStage
    status: Status
    created_at: Text
    data: dict = Field(default_factory=dict)


class EventsPage(ContractModel):
    schema_version: Literal['runtime-v1'] = 'runtime-v1'
    events: list[RuntimeEvent]
    next_after: StrictInt


class PendingInput(ContractModel):
    pending_input_id: Id
    kind: Literal['constraints', 'input_review', 'print_review', 'repair_request', 'repair_confirmation', 'slicer']
    mesh_version: Id | None = None
    questions: list[Text] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


class GenerationDelivery(ContractModel):
    artifact_id: Id
    mesh_version: Id
    independent_readback: Literal[True]
    print_check: Literal['passed','failed','not_run']
    print_certified: Literal[False] = False
    repair_attempts: Annotated[StrictInt, Field(ge=0,le=2)] = 0
    dimensions_mm: Dimensions
    warnings: list[Text] = Field(default_factory=list)


class GenerationTaskResponse(ModelTaskResponse):
    """GLB完成语义与公共1.0.0的打印成功语义分开。"""
    schema_version: Literal['generation-v1'] = 'generation-v1'
    delivery: GenerationDelivery | None = None
    orientation_source: Literal['user_parameter','backend_z_up'] = 'backend_z_up'

    def _require_complete(self, artifacts):
        delivery=self.delivery
        if delivery is None or delivery.mesh_version!=self.data.state.mesh_version:
            raise ValueError('GLB完成必须绑定实际交付版本')
        artifact=artifacts.get(delivery.artifact_id)
        if artifact is None or artifact.mesh_version!=delivery.mesh_version or not artifact.relative_path.endswith('.glb'):
            raise ValueError('GLB交付必须引用本任务实际GLB')
        if not any(a.kind=='quality_report' and a.mesh_version==delivery.mesh_version for a in artifacts.values()):
            raise ValueError('GLB完成必须附带同版本质量报告')
        inspection=self.data.inspection
        actual=print_check_for(inspection)
        if inspection is not None and inspection.mesh_version!=delivery.mesh_version:raise ValueError('GLB检查版本不匹配')
        if delivery.print_check!=actual:raise ValueError('打印检查标签与实际证据不符')
        if self.data.slicer_confirmation is not None:raise ValueError('自动GLB交付不能声称实际切片确认')


def print_check_for(inspection):
    if inspection is None:return 'not_run'
    if any(c.status=='fail' for c in inspection.checks):return 'failed'
    if any(c.status=='not_run' for c in inspection.checks):return 'not_run'
    return 'passed' if inspection.ready_for_print else 'failed'


class RuntimeTask(ContractModel):
    """扩展查询；response依任务快照返回打印契约或generation-v1。"""
    response: ModelTaskResponse | GenerationTaskResponse
    pending: PendingInput | None = None
    resources: dict = Field(default_factory=dict)
    artifact_frames: dict[Id, Literal['z_up', 'y_up']] = Field(default_factory=dict)


class ParsedRequirements(ContractModel):
    height_value: Positive | None = None
    height_unit: Literal['mm', 'cm'] | None = None
    scale_source: Literal['user_target', 'measured_object'] | None = None
    up_axis: Literal['x', 'y', 'z', '-x', '-y', '-z'] | None = None
    questions: list[Text] = Field(default_factory=list, max_length=8)
    explanation: Annotated[str, Field(max_length=3000)] = ''
