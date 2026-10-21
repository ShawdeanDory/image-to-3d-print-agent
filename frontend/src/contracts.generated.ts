// 自动生成：python scripts/tools/export_frontend_types.py；不要手改。
export type ArtifactRecord = {
  "artifact_id": string;
  "created_at": string;
  "derived_from"?: Array<string>;
  "kind": "input_image" | "foreground_image" | "raw_mesh" | "repaired_mesh" | "candidate_stl" | "quality_report" | "inspection_report" | "slicer_preview" | "slicer_confirmation" | "log";
  "mesh_version"?: (string | null);
  "relative_path": string;
  "run_id": string;
  "unit"?: ("mm" | "unitless" | null);
};

export type AssetRecord = {
  "asset_id": string;
  "byte_count": number;
  "content_type": "image/png" | "image/jpeg";
  "height": number;
  "relative_path": string;
  "width": number;
};

export type BudgetPlan = {
  "budget_id": string;
  "confirmed_by"?: (string | null);
  "cost_limit_cny"?: (number | null);
  "inference_timeout_s"?: (number | null);
  "max_retries"?: (number | null);
  "preparation_timeout_s"?: (number | null);
  "reason"?: (string | null);
  "state": "draft" | "confirmed";
};

export type CheckResult = {
  "details"?: Record<string, JsonValue>;
  "evidence_artifact_id"?: (string | null);
  "name": string;
  "status": "pass" | "fail" | "warn" | "not_run";
  "threshold"?: JsonValue;
  "tool_version"?: (string | null);
  "unit"?: (string | null);
  "value"?: JsonValue;
};

export type ConstraintsInput = {
  "accept_suggestions"?: boolean;
  "height_unit"?: ("mm" | "cm" | null);
  "height_value"?: (number | null);
  "kind": "constraints";
  "mesh_version"?: (string | null);
  "orientation"?: (Orientation | null);
  "pending_input_id": string;
  "scale_evidence_id"?: (string | null);
  "scale_source"?: ("user_target" | "measured_object" | null);
  "submission_id": string;
};

export type CreateTask = {
  "backend"?: ("triposr" | "trellis2_candidate" | null);
  "reconstruction_profile"?: ("official" | "course_fast" | null);
  "request": ModelTaskRequest;
};

export type DatasetCase = {
  "asset_path": string;
  "case_id": string;
  "category": "normal" | "boundary";
  "expected": "candidate" | "wait" | "reject" | "review" | "tool_failure";
  "expected_reason": string;
  "image_should_decode": boolean;
  "license": string;
  "mask_path"?: (string | null);
  "object_group": string;
  "reference_mesh"?: (string | null);
  "request": Record<string, JsonValue>;
  "request_should_validate"?: boolean;
  "result_status"?: "not_run";
  "source_kind": "authorized_p0" | "procedural_cpu" | "boundary_fixture";
  "source_ref": string;
  "split": "development" | "evaluation" | "holdout";
};

export type DatasetManifest = {
  "cases": Array<DatasetCase>;
  "dataset_version": string;
  "policy": SplitPolicy;
  "schema_version"?: "1.0.0";
  "scope": string;
};

export type ErrorInfo = {
  "code": "INVALID_IMAGE" | "INVALID_ARGUMENT" | "MODEL_NOT_CONFIGURED" | "TOOL_UNAVAILABLE" | "GPU_OUT_OF_MEMORY" | "TOOL_TIMEOUT" | "MESH_NOT_PRINTABLE" | "REPAIR_LIMIT_REACHED" | "SLICER_VALIDATION_FAILED" | "WORKER_RESTARTED" | "REFERENCE_NOT_FOUND" | "STATE_CONFLICT" | "BUDGET_NOT_CONFIGURED";
  "details"?: Record<string, JsonValue>;
  "message": string;
};

export type EventsPage = {
  "events": Array<RuntimeEvent>;
  "next_after": number;
  "schema_version"?: "runtime-v1";
};

export type EvidenceRecord = {
  "artifact_id": string;
  "created_at": string;
  "evidence_id": string;
  "locator": string;
  "mesh_version"?: (string | null);
  "run_id": string;
  "source_id": string;
  "source_type": "input" | "tool" | "measurement" | "human";
  "summary": string;
};

export type ExperimentRecord = {
  "artifact_ids"?: Array<string>;
  "backend_id": string;
  "baseline_run_id"?: (string | null);
  "budget_ref"?: (string | null);
  "case_id": string;
  "changed_factor"?: (string | null);
  "command"?: Array<string>;
  "comparison_group_id"?: (string | null);
  "created_at": string;
  "dataset_version": string;
  "environment_ref"?: (string | null);
  "error"?: (ErrorInfo | null);
  "evidence_ids"?: Array<string>;
  "evidence_origin": "user_submitted" | "agent_executed" | "offline_fixture";
  "executed_by": string;
  "exit_code"?: (number | null);
  "experiment_id": string;
  "experiment_type": "official_inference" | "model_comparison" | "repair_comparison" | "workflow_comparison";
  "hardware_ref"?: (string | null);
  "metrics"?: Array<MetricValue>;
  "metrics_protocol_version": string;
  "parameters"?: Record<string, JsonValue>;
  "preprocessing_ref"?: (string | null);
  "printer_profile_id"?: (string | null);
  "project_commit"?: (string | null);
  "release_frozen"?: boolean;
  "release_ref"?: (string | null);
  "run_id": string;
  "schema_version"?: "1.0.0";
  "seed": number;
  "split": "development" | "evaluation" | "holdout";
  "status": "succeeded" | "failed" | "not_run";
  "submodule_revisions"?: Record<string, string>;
  "upstream_commit"?: (string | null);
  "weights_revision"?: (string | null);
};

export type GenerationDelivery = {
  "artifact_id": string;
  "dimensions_mm": Array<number>;
  "independent_readback": true;
  "mesh_version": string;
  "print_certified"?: false;
  "print_check": "passed" | "failed" | "not_run";
  "repair_attempts"?: number;
  "warnings"?: Array<string>;
};

export type GenerationTaskResponse = {
  "artifacts"?: Array<ArtifactRecord>;
  "data": TaskData;
  "datasets"?: Array<string>;
  "delivery"?: (GenerationDelivery | null);
  "error"?: (ErrorInfo | null);
  "events"?: Array<string>;
  "evidence"?: Array<EvidenceRecord>;
  "orientation_source"?: "user_parameter" | "backend_z_up";
  "request_id": string;
  "run_id": string;
  "schema_version"?: "generation-v1";
  "status": "queued" | "running" | "waiting_for_input" | "cancel_requested" | "succeeded" | "failed" | "cancelled";
  "task_id"?: "image_to_3d_print";
  "warnings"?: Array<string>;
};

export type ImageReviewInput = {
  "complete_subject": boolean;
  "decision": "accepted" | "replace_image" | "uncertain";
  "foreground_artifact_id": string;
  "foreground_correct": boolean;
  "kind": "input_review";
  "mesh_version"?: (string | null);
  "pending_input_id": string;
  "simple_nonfunctional_ornament": boolean;
  "submission_id": string;
};

export type JsonValue = unknown;

export type MeshInspection = {
  "boundary_edge_count": number;
  "checks"?: Array<CheckResult>;
  "component_count": number;
  "dimensions_mm"?: (Array<number> | null);
  "mesh_version": string;
  "non_manifold_edge_count": number;
  "non_manifold_vertex_count": number;
  "normals_consistent": boolean;
  "unit": "mm" | "unitless";
  "volume_mm3"?: (number | null);
  "volume_reason"?: (string | null);
  "watertight": boolean;
};

export type MetricValue = {
  "name": string;
  "reason"?: (string | null);
  "status": "measured" | "not_run" | "unknown";
  "unit": string;
  "value"?: (number | null);
};

export type ModelTaskRequest = {
  "description"?: string;
  "height_unit"?: ("mm" | "cm" | null);
  "height_value"?: (number | null);
  "image_asset_id": string;
  "orientation"?: Orientation;
  "printer_profile_id": string;
  "scale_evidence_id"?: (string | null);
  "scale_source"?: ("user_target" | "measured_object" | null);
  "schema_version"?: "1.0.0";
};

export type ModelTaskResponse = {
  "artifacts"?: Array<ArtifactRecord>;
  "data": TaskData;
  "datasets"?: Array<string>;
  "error"?: (ErrorInfo | null);
  "events"?: Array<string>;
  "evidence"?: Array<EvidenceRecord>;
  "request_id": string;
  "run_id": string;
  "schema_version"?: "1.0.0";
  "status": "queued" | "running" | "waiting_for_input" | "cancel_requested" | "succeeded" | "failed" | "cancelled";
  "task_id"?: "image_to_3d_print";
  "warnings"?: Array<string>;
};

export type Orientation = {
  "confirmed"?: boolean;
  "up_axis"?: ("x" | "y" | "z" | "-x" | "-y" | "-z" | null);
};

export type ParsedRequirements = {
  "explanation"?: string;
  "height_unit"?: ("mm" | "cm" | null);
  "height_value"?: (number | null);
  "questions"?: Array<string>;
  "scale_source"?: ("user_target" | "measured_object" | null);
  "up_axis"?: ("x" | "y" | "z" | "-x" | "-y" | "-z" | null);
};

export type PendingInput = {
  "details"?: Record<string, unknown>;
  "kind": "constraints" | "input_review" | "print_review" | "repair_request" | "repair_confirmation" | "slicer";
  "mesh_version"?: (string | null);
  "pending_input_id": string;
  "questions"?: Array<string>;
};

export type PrintReviewInput = {
  "bed_confirmed": boolean;
  "component_count"?: (number | null);
  "components_confirmed"?: boolean;
  "kind": "print_review";
  "mesh_version"?: (string | null);
  "pending_input_id": string;
  "preview_artifact_id": string;
  "submission_id": string;
};

export type PrinterProfile = {
  "build_volume_mm"?: (Array<number> | null);
  "layer_height_mm": number;
  "material": "PLA";
  "min_wall_mm": number;
  "nozzle_mm": number;
  "process": "FDM";
  "profile_id": string;
  "profile_kind": "demo" | "verified_device";
  "slicer_version": string;
  "supports_policy": "human_review";
  "version": string;
};

export type RepairConfirmInput = {
  "accepted": boolean;
  "kind": "repair_confirmation";
  "mesh_version"?: (string | null);
  "pending_input_id": string;
  "proposal_id": string;
  "submission_id": string;
};

export type RepairRequestInput = {
  "kind": "repair_request";
  "mesh_version"?: (string | null);
  "pending_input_id": string;
  "request"?: (StructureRequest | null);
  "stop"?: boolean;
  "submission_id": string;
};

export type RuntimeEvent = {
  "created_at": string;
  "data"?: Record<string, unknown>;
  "event_id": number;
  "kind": string;
  "run_id": string;
  "stage": "input" | "preprocess" | "scale" | "reconstruct" | "repair" | "inspect" | "export" | "slicer" | "complete";
  "status": "queued" | "running" | "waiting_for_input" | "cancel_requested" | "succeeded" | "failed" | "cancelled";
};

export type RuntimeTask = {
  "artifact_frames"?: Record<string, "z_up" | "y_up">;
  "pending"?: (PendingInput | null);
  "resources"?: Record<string, unknown>;
  "response": (ModelTaskResponse | GenerationTaskResponse);
};

export type SlicerConfirmation = {
  "confirmation_artifact_id": string;
  "dimensions_mm": Array<number>;
  "layer_preview_asset_id": string;
  "mesh_version": string;
  "notes"?: string;
  "pending_input_id": string;
  "printer_profile_id": string;
  "result": "pass" | "fail";
  "slicer_version": string;
  "supports_enabled": boolean;
};

export type SlicerInput = {
  "bed_confirmed": boolean;
  "dimensions_mm": Array<number>;
  "kind": "slicer";
  "layer_preview_asset_id": string;
  "mesh_version": string;
  "model_preview_confirmed": boolean;
  "notes"?: string;
  "pending_input_id": string;
  "printer_profile_id": string;
  "result": "pass" | "fail";
  "slicer_version": string;
  "submission_id": string;
  "support_reviewed": boolean;
  "supports_enabled": boolean;
};

export type SplitPolicy = {
  "cases_per_split": number;
  "normal_per_split": number;
};

export type StructureRequest = {
  "max_perimeter_mm"?: number;
  "min_wall_mm"?: number;
  "operation": "fill_small_holes" | "remove_components" | "simplify";
  "remove_components"?: Array<number>;
  "target_faces"?: number;
};

export type TaskData = {
  "inspection"?: (MeshInspection | null);
  "printer_profile": PrinterProfile;
  "request": ModelTaskRequest;
  "slicer_confirmation"?: (SlicerConfirmation | null);
  "state": WorkflowState;
};

export type ToolResult = {
  "artifact_ids"?: Array<string>;
  "data"?: Record<string, JsonValue>;
  "error"?: (ErrorInfo | null);
  "evidence_ids"?: Array<string>;
  "run_id": string;
  "succeeded": boolean;
  "tool_name": "preprocess" | "reconstruct" | "repair" | "inspect" | "export" | "slice";
};

export type WorkflowState = {
  "artifacts"?: Array<string>;
  "checks"?: Array<CheckResult>;
  "error"?: (ErrorInfo | null);
  "mesh_version"?: (string | null);
  "pending_input_id"?: (string | null);
  "pending_input_type"?: ("height" | "height_unit" | "scale_source" | "orientation" | "replacement_image" | "repair_confirmation" | "slicer_confirmation" | null);
  "repair_round"?: number;
  "run_id": string;
  "stage": "input" | "preprocess" | "scale" | "reconstruct" | "repair" | "inspect" | "export" | "slicer" | "complete";
  "status": "queued" | "running" | "waiting_for_input" | "cancel_requested" | "succeeded" | "failed" | "cancelled";
  "warnings"?: Array<string>;
};
