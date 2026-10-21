"""运行时v1扩展；公共1.0.0模型与状态保持兼容。"""
from typing import Annotated, Literal, Union
from uuid import UUID
from pydantic import Field, StrictBool, StrictInt
from .schemas.common import ContractModel, Id, Text, Orientation, Positive, Dimensions, Status
from .schemas.task import ModelTaskRequest, ModelTaskResponse, WorkflowState
from .geometry.structure import StructureRequest

Backend = Literal['triposr', 'trellis2_candidate']
WorkflowStage = WorkflowState.model_fields['stage'].annotation


class CreateTask(ContractModel):
    request: ModelTaskRequest
    backend: Backend | None = None


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


class RuntimeTask(ContractModel):
    """只用于扩展查询；普通查询仍返回原ModelTaskResponse。"""
    response: ModelTaskResponse
    pending: PendingInput | None = None
    resources: dict = Field(default_factory=dict)


class ParsedRequirements(ContractModel):
    height_value: Positive | None = None
    height_unit: Literal['mm', 'cm'] | None = None
    scale_source: Literal['user_target', 'measured_object'] | None = None
    up_axis: Literal['x', 'y', 'z', '-x', '-y', '-z'] | None = None
    questions: list[Text] = Field(default_factory=list, max_length=8)
    explanation: Annotated[str, Field(max_length=3000)] = ''
