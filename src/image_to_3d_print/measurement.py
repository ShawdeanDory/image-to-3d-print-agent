"""不加载神经模型的CPU几何投影和轮廓测量；尚非打印检查器。"""
from datetime import datetime, timezone
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import time
from typing import Literal
from uuid import UUID, uuid4

from PIL import Image, ImageChops, ImageDraw
from pydantic import Field, model_validator

from .schemas.common import (
    ArtifactRecord, ContractModel, ErrorInfo, EvidenceRecord, RelativePath, ToolResult,
    safe_relative_path,
)
from .schemas.experiment import MetricValue
from .schemas.validation import resolve_artifact_path

VERSION = "cpu_silhouette_0.1.0"
IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


class MeasurementError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class MeasurementRequest(ContractModel):
    mesh: RelativePath
    input_mask: RelativePath | None = None
    backend: Literal["fixture", "triposr", "trellis2_candidate"] = "fixture"
    mapping: Literal["known_fixture", "unverified"] = "unverified"
    mapping_evidence: str | None = None
    rotation: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]] = IDENTITY

    @model_validator(mode="after")
    def rigid_and_grounded(self):
        r = self.rotation
        for i in range(3):
            for j in range(3):
                if abs(sum(r[i][k] * r[j][k] for k in range(3)) - (i == j)) > 1e-6:
                    raise ValueError("变换必须为正交刚性旋转，不能非等比缩放")
        determinant = sum(r[0][i] * (r[1][(i+1)%3]*r[2][(i+2)%3] - r[1][(i+2)%3]*r[2][(i+1)%3]) for i in range(3))
        if abs(determinant - 1) > 1e-6:
            raise ValueError("旋转不能包含镜像")
        if self.mapping == "known_fixture" and (self.backend != "fixture" or self.input_mask is None or not self.mapping_evidence or not self.mapping_evidence.strip()):
            raise ValueError("本入口仅允许有来源的固定几何确认映射；真实后端仍待校准")
        return self


class CameraPolicy(ContractModel):
    position: tuple[float, float, float] = (0., -3., 0.)
    target: tuple[float, float, float] = (0., 0., 0.)
    up: tuple[float, float, float] = (0., 0., 1.)
    orthographic_scale: float = Field(default=2.2, gt=0)
    canvas_px: int = Field(default=256, ge=16, le=4096)
    foreground_long_side_px: int = Field(default=224, ge=1)

    @model_validator(mode="after")
    def fits(self):
        if self.foreground_long_side_px > self.canvas_px:
            raise ValueError("轮廓长边不能超过画布")
        forward = [self.target[i] - self.position[i] for i in range(3)]
        cross = [forward[1]*self.up[2]-forward[2]*self.up[1], forward[2]*self.up[0]-forward[0]*self.up[2], forward[0]*self.up[1]-forward[1]*self.up[0]]
        if sum(v*v for v in cross) < 1e-12:
            raise ValueError("相机方向与朝上方向不能平行或为零")
        return self


def load_policy(root):
    try:
        config = json.loads(resolve_artifact_path(root, "evals/protocol_v1.json").read_text(encoding="utf-8"))
        s, p = config["silhouette"], config["preprocessing"]
    except (OSError, ValueError, KeyError) as exc:
        raise MeasurementError("INVALID_ARGUMENT", "测量协议配置缺失或无效") from exc
    if (config["protocol_version"] != "1.0.0" or s["camera_type"] != "orthographic"
            or s["mesh_normalization"] != "center_bbox_and_isotropic_longest_extent_2"
            or s["mask_normalization"] != "tight_bbox_isotropic_224_center_256"
            or p["alpha_threshold"] != 128):
        raise MeasurementError("INVALID_ARGUMENT", "该测量器不支持此协议，不能静默换口径")
    return CameraPolicy(**{k: s[k] for k in ("position", "target", "up", "orthographic_scale")},
                        canvas_px=p["canvas_px"], foreground_long_side_px=p["foreground_long_side_px"])


def binary_mask(image):
    if image.mode == "RGBA":
        image = image.getchannel("A")
    elif image.mode not in {"1", "L"}:
        raise MeasurementError("INVALID_IMAGE", "需要单通道蒙版或RGBA，不能把RGB亮度猜作前景")
    return image.convert("L").point(lambda value: 255 if value >= 128 else 0)


def normalize_mask(image, policy=None):
    policy = policy or CameraPolicy()
    image = binary_mask(image)
    bbox = image.getbbox()
    if bbox is None:
        raise MeasurementError("INVALID_IMAGE", "空前景蒙版不能参与轮廓测量")
    cropped = image.crop(bbox)
    ratio = policy.foreground_long_side_px / max(cropped.size)
    size = tuple(max(1, int(math.floor(value * ratio + .5))) for value in cropped.size)
    resized = cropped.resize(size, Image.Resampling.NEAREST)
    canvas = Image.new("L", (policy.canvas_px, policy.canvas_px))
    canvas.paste(resized, tuple((policy.canvas_px-value)//2 for value in size))
    return canvas


def mask_iou(first, second):
    a, b = binary_mask(first), binary_mask(second)
    if a.size != b.size:
        raise MeasurementError("INVALID_ARGUMENT", "IoU输入画布尺寸不一致")
    if a.getbbox() is None or b.getbbox() is None:
        return MetricValue(name="silhouette_iou", status="unknown", unit="ratio", reason="empty_mask")
    intersection = sum(ImageChops.darker(a, b).getdata()) // 255
    union = sum(ImageChops.lighter(a, b).getdata()) // 255
    return MetricValue(name="silhouette_iou", status="measured", value=intersection/union, unit="ratio")


def render_silhouette(vertices, faces, rotation=IDENTITY, policy=None):
    """正交投影全部不透明三角形的并集，无深度/光照/材质操作。"""
    import numpy as np
    policy = policy or CameraPolicy()
    v, f = np.asarray(vertices, dtype=float), np.asarray(faces)
    if (v.ndim != 2 or v.shape[1:] != (3,) or not len(v) or not np.isfinite(v).all()
            or f.ndim != 2 or f.shape[1:] != (3,) or not len(f)
            or not np.issubdtype(f.dtype, np.integer) or f.min() < 0 or f.max() >= len(v)):
        raise MeasurementError("INVALID_ARGUMENT", "网格须非空、坐标有限、三角形索引有效")
    # 同样校验直接调用的旋转，不允许绕过请求模型改变形状。
    MeasurementRequest(mesh="mesh.obj", input_mask="mask.png", rotation=rotation)
    v = v @ np.asarray(rotation).T
    if not np.isfinite(v).all():
        raise MeasurementError("INVALID_ARGUMENT", "旋转后坐标溢出")
    low, high = v.min(axis=0), v.max(axis=0)
    span = float((high-low).max())
    if not math.isfinite(span) or span <= 1e-12:
        raise MeasurementError("INVALID_ARGUMENT", "网格包围盒退化")
    center, scale = (low+high)/2, 2/span
    normalized = (v-center)*scale
    forward = np.asarray(policy.target)-np.asarray(policy.position)
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, policy.up); right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    x = normalized @ right
    y = normalized @ up
    depth = (normalized-np.asarray(policy.position)) @ forward
    if depth.min() <= 0 or max(abs(x).max(), abs(y).max()) >= policy.orthographic_scale/2:
        raise MeasurementError("INVALID_ARGUMENT", "固定相机不能完整覆盖网格，不能静默裁掉形状")
    pixels = np.column_stack(((x/policy.orthographic_scale+.5)*policy.canvas_px,
                             (.5-y/policy.orthographic_scale)*policy.canvas_px))
    image = Image.new("L", (policy.canvas_px, policy.canvas_px))
    draw = ImageDraw.Draw(image)
    for indices in f:
        points = pixels[indices]
        area = (points[1,0]-points[0,0])*(points[2,1]-points[0,1]) - (points[1,1]-points[0,1])*(points[2,0]-points[0,0])
        if abs(area) > 1e-12:
            draw.polygon([tuple(point) for point in points], fill=255)
    if image.getbbox() is None:
        raise MeasurementError("INVALID_ARGUMENT", "投影为空或所有面均退化")
    return image, {"vertex_count": len(v), "face_count": len(f), "original_extents": (high-low).tolist(),
                   "center_after_rotation": center.tolist(), "isotropic_scale": scale,
                   "rotation": [list(row) for row in rotation], "unit": "unitless",
                   "rasterizer": "Pillow_integer_triangle_union", "scene_transforms": "applied_by_trimesh"}


class MeasurementReport(ContractModel):
    version: Literal["cpu_silhouette_0.1.0"] = VERSION
    protocol_version: Literal["1.0.0"] = "1.0.0"
    run_id: UUID
    request: MeasurementRequest
    camera: CameraPolicy
    metric: MetricValue
    tool: ToolResult
    artifacts: list[ArtifactRecord]
    evidence: list[EvidenceRecord]
    geometry: dict = Field(default_factory=dict)
    seconds: float = Field(ge=0)
    runtime: dict[str, str]
    gpu_used: Literal[False] = False
    model_generated: Literal[False] = False


def measure(root, request, output_relative):
    root = Path(root).resolve()
    safe_relative_path(output_relative)
    output = (root/output_relative).resolve()
    if not output.is_relative_to(root):
        raise ValueError("输出越过项目目录")
    output.mkdir(parents=True, exist_ok=False)
    started, run_id, now = time.perf_counter(), uuid4(), datetime.now(timezone.utc)
    artifacts, geometry, error = [], {}, None
    policy = CameraPolicy()
    metric = MetricValue(name="silhouette_iou", status="not_run", unit="ratio", reason="not_executed")

    def artifact(name, filename):
        artifacts.append(ArtifactRecord(artifact_id=name, run_id=run_id, mesh_version="existing_mesh",
            kind="inspection_report", relative_path=f"{output_relative}/{filename}", created_at=now, unit="unitless"))

    try:
        policy = load_policy(root)
        try:
            mesh_path = resolve_artifact_path(root, request.mesh)
            image_path = resolve_artifact_path(root, request.input_mask) if request.input_mask else None
        except ValueError as exc:
            raise MeasurementError("REFERENCE_NOT_FOUND", str(exc)) from exc
        input_mask = None
        try:
            if image_path is not None:
                with Image.open(image_path) as source:
                    if source.width > 4096 or source.height > 4096:
                        raise MeasurementError("INVALID_IMAGE", "蒙版尺寸超过4096像素")
                    input_mask = normalize_mask(source, policy)
        except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
            raise MeasurementError("INVALID_IMAGE", "蒙版损坏或无法解码") from exc
        import trimesh
        try:
            mesh = trimesh.load(mesh_path, force="mesh", process=False)
            projection, geometry = render_silhouette(mesh.vertices, mesh.faces, request.rotation, policy)
        except (OSError, ValueError, AttributeError, TypeError, IndexError) as exc:
            if isinstance(exc, MeasurementError):
                raise
            raise MeasurementError("INVALID_ARGUMENT", "网格无法读取或不是有效三角网格") from exc
        projected_mask = normalize_mask(projection, policy)
        images = [("projection", projection), ("projected_mask", projected_mask)]
        if input_mask is not None:
            overlay = Image.merge("RGB", (input_mask, projected_mask, Image.new("L", input_mask.size)))
            images.extend([("input_mask", input_mask), ("overlay", overlay)])
        for name, image in images:
            image.save(output/f"{name}.png")
            artifact(name, f"{name}.png")
        if request.mapping == "known_fixture":
            metric = mask_iou(input_mask, projected_mask)
        else:
            reason = "backend_to_input_mapping_unverified" if input_mask is not None else "input_mask_unavailable_and_mapping_unverified"
            metric = MetricValue(name="silhouette_iou", status="not_run", unit="ratio", reason=reason)
    except MeasurementError as exc:
        error = ErrorInfo(code=exc.code, message=str(exc))
        metric = MetricValue(name="silhouette_iou", status="not_run", unit="ratio", reason=str(exc))
    artifact("measurement_report", "report.json")
    evidence = EvidenceRecord(evidence_id="cpu_measurement", source_type="measurement", source_id="cpu_silhouette",
        run_id=run_id, mesh_version="existing_mesh", artifact_id="measurement_report", locator="metric",
        created_at=now, summary="CPU几何投影与轮廓诊断；不是打印合格结论")
    tool = ToolResult(run_id=run_id, tool_name="inspect", succeeded=error is None,
        artifact_ids=[item.artifact_id for item in artifacts], evidence_ids=[evidence.evidence_id], error=error,
        data={"measurement_kind": "silhouette_diagnostic", "metric": metric.model_dump(mode="json"), "printability": "not_evaluated"})
    report = MeasurementReport(run_id=run_id, request=request, camera=policy, metric=metric, tool=tool,
        artifacts=artifacts, evidence=[evidence], geometry=geometry, seconds=time.perf_counter()-started,
        runtime={"python": platform.python_version(), **{name: importlib.metadata.version(name) for name in ("Pillow", "pydantic", "numpy", "trimesh")}})
    (output/"report.json").write_text(report.model_dump_json(indent=2)+"\n", encoding="utf-8")
    return report
