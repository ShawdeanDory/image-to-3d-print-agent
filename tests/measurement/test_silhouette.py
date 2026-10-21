"""CPU测量的已知答案、坐标、错误和文件边界。"""
import json
from pathlib import Path

from PIL import Image
import pytest
from pydantic import ValidationError

from image_to_3d_print.measurement import (
    MeasurementRequest, MeasurementReport, MeasurementError,
    normalize_mask, mask_iou, render_silhouette, measure,
)


def mask(points, size=(4, 4)):
    image = Image.new("L", size)
    for point in points:
        image.putpixel(point, 255)
    return image


def test_known_iou_answers():
    a = mask([(0, 0), (1, 0)])
    assert mask_iou(a, a).value == 1
    assert mask_iou(a, mask([(2, 0), (3, 0)])).value == 0
    assert mask_iou(a, mask([(1, 0), (2, 0)])).value == pytest.approx(1 / 3)


def test_empty_is_unknown_and_size_mismatch_rejected():
    assert mask_iou(mask([]), mask([])).status == "unknown"
    assert mask_iou(mask([]), mask([])).value is None
    with pytest.raises(MeasurementError):
        mask_iou(mask([]), mask([], (5, 5)))


def test_normalization_preserves_aspect_and_centers():
    image = Image.new("L", (20, 30))
    image.paste(255, (3, 7, 13, 27))
    result = normalize_mask(image)
    assert result.size == (256, 256)
    assert result.getbbox() == (72, 16, 184, 240)
    assert set(result.getdata()) == {0, 255}


def test_alpha_threshold_and_empty_normalization():
    image = Image.new("RGBA", (2, 2), (255, 0, 0, 127))
    with pytest.raises(MeasurementError):
        normalize_mask(image)
    image.putpixel((0, 0), (0, 0, 0, 128))
    assert normalize_mask(image).getbbox() == (16, 16, 240, 240)
    with pytest.raises(MeasurementError):
        normalize_mask(Image.new("RGB", (2, 2), "white"))


VERTICES = [(-1, 0, -1), (1, 0, -1), (-1, 0, 1)]
FACES = [(0, 1, 2)]
IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def test_asymmetric_triangle_projection_and_copy():
    image, info = render_silhouette(VERTICES, FACES, IDENTITY)
    assert image.getpixel((40, 210)) == 255
    assert image.getpixel((210, 40)) == 0
    assert image.getpixel((40, 80)) == 255
    assert info["original_extents"] == [2., 0., 2.]
    assert VERTICES[0] == (-1, 0, -1)


def test_axis_rotation_is_applied_once():
    # 绕Y轴180度，原左上直角移至右下。
    image, _ = render_silhouette(VERTICES, FACES, ((-1.,0.,0.),(0.,1.,0.),(0.,0.,-1.)))
    assert image.getpixel((210, 40)) == 255
    assert image.getpixel((40, 210)) == 0


def test_trellis_glb_inverse_restores_known_axes():
    exported = [(x, z, -y) for x, y, z in VERTICES]
    inverse = ((1.,0.,0.),(0.,0.,-1.),(0.,1.,0.))
    image, info = render_silhouette(exported, FACES, inverse)
    assert info["original_extents"] == [2.,0.,2.]
    assert image.getpixel((40,210)) == 255
    assert image.getpixel((210,40)) == 0


@pytest.mark.parametrize("vertices,faces", [([], []), ([(0,0,float('nan'))], [(0,0,0)]),
    (VERTICES, [(0,1,3)]), ([(0,0,0)], [(0,0,0)])])
def test_invalid_mesh_rejected(vertices, faces):
    with pytest.raises(MeasurementError):
        render_silhouette(vertices, faces, IDENTITY)


def request(**changes):
    return MeasurementRequest(mesh="mesh.obj", input_mask="input.png", **changes)


@pytest.mark.parametrize("changes", [
    {"mesh": "../outside.obj"}, {"input_mask": "C:/secret.png"},
    {"rotation": ((2,0,0),(0,1,0),(0,0,1))},
    {"rotation": ((-1,0,0),(0,1,0),(0,0,1))},
    {"backend": "trellis2_candidate", "mapping": "known_fixture", "mapping_evidence": "fake"},
    {"mapping": "known_fixture"},
])
def test_request_boundaries(changes):
    values = {"mesh": "mesh.obj", "input_mask": "input.png", **changes}
    with pytest.raises(ValidationError):
        MeasurementRequest(**values)


def prepare(root):
    protocol = Path(__file__).resolve().parents[2] / "evals/protocol_v1.json"
    (root / "evals").mkdir()
    (root / "evals/protocol_v1.json").write_bytes(protocol.read_bytes())
    (root / "mesh.obj").write_text("v -1 0 -1\nv 1 0 -1\nv -1 0 1\nf 1 2 3\n", encoding="utf-8")
    image, _ = render_silhouette(VERTICES, FACES, IDENTITY)
    image.save(root / "input.png")


def test_known_fixture_measurement_and_evidence(tmp_path):
    prepare(tmp_path)
    original = (tmp_path / "mesh.obj").read_bytes()
    report = measure(tmp_path, request(mapping="known_fixture", mapping_evidence="analytic_triangle_v1"), "result")
    assert report.metric.value == 1
    assert report.tool.succeeded
    assert report.geometry["vertex_count"] == 3
    assert (tmp_path / "mesh.obj").read_bytes() == original
    saved = MeasurementReport.model_validate_json((tmp_path / "result/report.json").read_text(encoding="utf-8"))
    assert saved == report
    for artifact in saved.artifacts:
        assert (tmp_path / artifact.relative_path).is_file()
        assert artifact.run_id == report.run_id
    assert set(report.tool.evidence_ids) == {item.evidence_id for item in report.evidence}
    assert report.evidence[0].artifact_id in report.tool.artifact_ids
    with pytest.raises(FileExistsError):
        measure(tmp_path, request(), "result")


def test_unverified_backend_never_gets_score(tmp_path):
    prepare(tmp_path)
    report = measure(tmp_path, request(backend="triposr"), "result")
    assert report.metric.status == "not_run"
    assert report.metric.value is None
    assert (tmp_path / "result/overlay.png").is_file()


def test_geometry_only_does_not_fabricate_input_mask(tmp_path):
    prepare(tmp_path)
    report = measure(tmp_path, MeasurementRequest(mesh="mesh.obj", backend="trellis2_candidate"), "result")
    assert report.tool.succeeded
    assert report.metric.status == "not_run" and report.metric.value is None
    assert "input_mask_unavailable" in report.metric.reason
    assert not (tmp_path / "result/input_mask.png").exists()


def test_scene_node_transform_is_preserved(tmp_path):
    import trimesh
    import numpy as np
    prepare(tmp_path)
    scene = trimesh.Scene()
    matrix = np.eye(4); matrix[0, 3] = 7
    scene.add_geometry(trimesh.Trimesh(vertices=VERTICES, faces=FACES, process=False), transform=matrix)
    (tmp_path / "scene.glb").write_bytes(scene.export(file_type="glb"))
    report = measure(tmp_path, MeasurementRequest(mesh="scene.glb", backend="triposr"), "result")
    assert report.geometry["center_after_rotation"] == pytest.approx([7, 0, 0])


@pytest.mark.parametrize("kind", ["missing", "empty", "corrupt", "bad_mesh"])
def test_failure_report_is_explicit(tmp_path, kind):
    prepare(tmp_path)
    if kind == "missing": (tmp_path / "input.png").unlink()
    elif kind == "empty": Image.new("L", (10,10)).save(tmp_path / "input.png")
    elif kind == "corrupt": (tmp_path / "input.png").write_bytes(b"broken")
    else: (tmp_path / "mesh.obj").write_text("broken", encoding="utf-8")
    report = measure(tmp_path, request(), "result")
    assert not report.tool.succeeded
    assert report.tool.error is not None
    assert report.metric.value is None
    assert report.metric.reason


@pytest.mark.parametrize("kind", ["missing", "unsupported"])
def test_protocol_is_not_silently_replaced(tmp_path, kind):
    prepare(tmp_path)
    path = tmp_path / "evals/protocol_v1.json"
    if kind == "missing": path.unlink()
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["protocol_version"] = "9.0.0"
        path.write_text(json.dumps(data), encoding="utf-8")
    report = measure(tmp_path, request(), "result")
    assert not report.tool.succeeded and report.tool.error.code == "INVALID_ARGUMENT"


def test_output_escape_and_input_symlink_rejected(tmp_path):
    prepare(tmp_path)
    with pytest.raises(ValueError):
        measure(tmp_path, request(), "../escape")
    outside = tmp_path.parent / (tmp_path.name + "_outside.obj")
    outside.write_text("anything", encoding="utf-8")
    (tmp_path / "mesh.obj").unlink()
    try:
        (tmp_path / "mesh.obj").symlink_to(outside)
    except OSError:
        pytest.skip("该系统不允许创建符号链接")
    report = measure(tmp_path, request(), "result")
    assert not report.tool.succeeded
    assert report.tool.error.code == "REFERENCE_NOT_FOUND"
