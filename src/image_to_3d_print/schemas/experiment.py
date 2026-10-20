"""实验记录、预算与固定数据清单；只做校验，不执行实验。"""
from collections import Counter
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, StrictBool, StrictInt, StringConstraints, model_validator

from .common import ContractModel, ErrorInfo, Id, NonNegative, RelativePath, SCHEMA_VERSION, Text
from .task import ModelTaskRequest

Revision = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{40}$")]
Split = Literal["development", "evaluation", "holdout"]


class MetricValue(ContractModel):
    name: Id
    status: Literal["measured", "not_run", "unknown"]
    value: NonNegative | None = None
    unit: Text
    reason: Text | None = None

    @model_validator(mode="after")
    def measurement_status(self):
        if self.status == "measured" and self.value is None:
            raise ValueError("实测指标必须有有限非负值")
        if self.status != "measured" and (self.value is not None or self.reason is None):
            raise ValueError("未测指标必须为null并说明原因")
        return self


class BudgetPlan(ContractModel):
    budget_id: Id
    state: Literal["draft", "confirmed"]
    preparation_timeout_s: Annotated[StrictInt, Field(gt=0)] | None = None
    inference_timeout_s: Annotated[StrictInt, Field(gt=0)] | None = None
    max_retries: Annotated[StrictInt, Field(ge=0, le=1)] | None = None
    cost_limit_cny: NonNegative | None = None
    confirmed_by: Id | None = None
    reason: Text | None = None

    def require_ready(self):
        if self.state != "confirmed" or any(value is None for value in [self.preparation_timeout_s, self.inference_timeout_s, self.max_retries, self.cost_limit_cny, self.confirmed_by]):
            raise ValueError("执行预算未确认或缺配置，不得进入P2执行")
        return self

    @model_validator(mode="after")
    def confirmed_values(self):
        if self.state == "confirmed": self.require_ready()
        return self


class ExperimentRecord(ContractModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    experiment_id: Id
    experiment_type: Literal["official_inference", "model_comparison", "repair_comparison", "workflow_comparison"]
    run_id: UUID
    case_id: Id
    dataset_version: Text
    split: Split
    executed_by: Id
    evidence_origin: Literal["user_submitted", "agent_executed", "offline_fixture"]
    created_at: AwareDatetime
    status: Literal["succeeded", "failed", "not_run"]
    backend_id: Id
    project_commit: Revision | None = None
    upstream_commit: Revision | None = None
    submodule_revisions: dict[Id, Revision] = Field(default_factory=dict)
    weights_revision: Revision | None = None
    environment_ref: Id | None = None
    hardware_ref: Id | None = None
    budget_ref: Id | None = None
    preprocessing_ref: Id | None = None
    printer_profile_id: Id | None = None
    metrics_protocol_version: Text
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    seed: Annotated[StrictInt, Field(ge=0)]
    command: list[Text] = Field(default_factory=list)
    exit_code: StrictInt | None = None
    artifact_ids: list[Id] = Field(default_factory=list)
    evidence_ids: list[Id] = Field(default_factory=list)
    metrics: list[MetricValue] = Field(default_factory=list)
    error: ErrorInfo | None = None
    comparison_group_id: Id | None = None
    baseline_run_id: UUID | None = None
    changed_factor: Text | None = None
    release_frozen: StrictBool = False
    release_ref: Id | None = None

    @model_validator(mode="after")
    def actual_run_evidence(self):
        if self.status == "not_run":
            if self.exit_code is not None or any(m.status == "measured" for m in self.metrics):
                raise ValueError("未运行不能携带退出码或实测指标")
            return self
        if self.split == "holdout" and (not self.release_frozen or self.release_ref is None):
            raise ValueError("保留集实际执行必须引用已冻结版本")
        if any(value is None for value in [self.project_commit, self.upstream_commit, self.weights_revision, self.environment_ref, self.hardware_ref, self.budget_ref, self.preprocessing_ref]) or not self.parameters or not self.command:
            raise ValueError("实际模型记录缺少版本、环境、硬件、预算、参数或命令")
        if self.status == "succeeded" and (self.exit_code != 0 or self.error is not None or not self.artifact_ids or not self.evidence_ids):
            raise ValueError("模型成功须有退出码0、真实产物和证据且无错误")
        if self.status == "failed" and self.error is None:
            raise ValueError("失败记录必须保留结构化错误")
        if self.experiment_type != "official_inference" and (self.comparison_group_id is None or self.baseline_run_id is None or self.changed_factor is None):
            raise ValueError("比较记录必须声明基线和变化因素")
        if len({m.name for m in self.metrics}) != len(self.metrics):
            raise ValueError("同口径指标名不能重复")
        return self


class DatasetCase(ContractModel):
    case_id: Id
    split: Split
    category: Literal["normal", "boundary"]
    object_group: Id
    asset_path: RelativePath
    mask_path: RelativePath | None = None
    source_kind: Literal["authorized_p0", "procedural_cpu", "boundary_fixture"]
    source_ref: Text
    license: Text
    image_should_decode: StrictBool
    request_should_validate: StrictBool = True
    request: dict[str, JsonValue]
    expected: Literal["candidate", "wait", "reject", "review", "tool_failure"]
    expected_reason: Text
    reference_mesh: RelativePath | None = None
    result_status: Literal["not_run"] = "not_run"

    @model_validator(mode="after")
    def declared_request(self):
        try:
            ModelTaskRequest.model_validate(self.request)
            valid = True
        except ValueError:
            valid = False
        if valid != self.request_should_validate:
            raise ValueError("请求结构与声明的预期校验结果不符")
        if self.category == "normal" and (not valid or not self.image_should_decode or self.expected != "candidate"):
            raise ValueError("正常用例须有合法请求/图像及候选网格预期")
        return self


class SplitPolicy(ContractModel):
    cases_per_split: Annotated[StrictInt, Field(gt=0)]
    normal_per_split: Annotated[StrictInt, Field(gt=0)]


class DatasetManifest(ContractModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    dataset_version: Text
    policy: SplitPolicy
    cases: list[DatasetCase]
    scope: Text

    @model_validator(mode="after")
    def unique_and_disjoint(self):
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError("case_id不能重复")
        groups, paths = {}, {}
        for case in self.cases:
            for mapping, key in [(groups, case.object_group), (paths, case.asset_path)]:
                if key in mapping and mapping[key] != case.split:
                    raise ValueError("同对象或同输入不能跨数据划分")
                mapping[key] = case.split
        for split in ["development", "evaluation", "holdout"]:
            cases = [c for c in self.cases if c.split == split]
            if len(cases) != self.policy.cases_per_split or sum(c.category == "normal" for c in cases) != self.policy.normal_per_split:
                raise ValueError("数据清单不满足声明的划分数量")
        return self
