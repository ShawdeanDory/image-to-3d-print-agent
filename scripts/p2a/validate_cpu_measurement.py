"""固定几何及已有GLB的CPU验收；不执行重建、evaluation或holdout。"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

os.environ["CUDA_VISIBLE_DEVICES"] = ""
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from PIL import Image, ImageDraw
from image_to_3d_print.measurement import MeasurementRequest, measure


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-root", type=Path, required=True)
    parser.add_argument("--output", default="results")
    args = parser.parse_args()
    started = time.perf_counter()
    results = ROOT/args.output
    results.mkdir(parents=True, exist_ok=False)
    Image.new("L", (16,16), 255).save(results/"square.png")
    pair = Image.new("L", (256,256))
    draw = ImageDraw.Draw(pair)
    # 两个10毫米方块，间距10毫米；由已知包围盒直接算出的投影矩形。
    draw.rectangle((11,89,89,166), fill=255)
    draw.rectangle((166,89,244,166), fill=255)
    pair.save(results/"pair.png")
    cases = [
        ("cube", ROOT, "fixtures/p1/geometry/cube_10mm.stl", f"{args.output}/square.png", "fixture", "known_fixture", "analytic_square_v1"),
        ("components", ROOT, "fixtures/p1/geometry/multiple_components.obj", f"{args.output}/pair.png", "fixture", "known_fixture", "analytic_two_rectangles_v1"),
        ("hamburger", args.existing_root, "runs/p2a-20261020-03/triposr-hamburger/raw_mesh.glb", "fixtures/p1/masks/hamburger.png", "triposr", "unverified", None),
        ("robot", args.existing_root, "runs/p2a-20261020-03/triposr-robot/raw_mesh.glb", "fixtures/p1/masks/robot.png", "triposr", "unverified", None),
        ("official_t", args.existing_root, "runs/p2a-gpu-20261020-01/official-default/sample.glb", None, "trellis2_candidate", "unverified", None),
    ]
    reports = []
    for name, root, mesh, mask, backend, mapping, evidence in cases:
        before = digest(root/mesh)
        # 固定上游postprocess.py:312-314导出为(x,z,-y)，此处仅撤销已知轴转换。
        rotation = ((1.,0.,0.),(0.,0.,-1.),(0.,1.,0.)) if backend == "trellis2_candidate" else ((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))
        if backend == "trellis2_candidate":
            evidence = "TRELLIS.2@75fbf018/postprocess.py:312-314 inverse; input-view mapping unverified"
        request = MeasurementRequest(mesh=mesh, input_mask=mask, backend=backend, mapping=mapping, mapping_evidence=evidence, rotation=rotation)
        relative = f"{args.output}/{name}" if root == ROOT else f"runs/cpu-measurement-20261021-01/{args.output}/{name}"
        report = measure(root, request, relative)
        assert report.tool.succeeded, report.tool.error
        assert before == digest(root/mesh), "原始网格被改写"
        if backend == "fixture":
            assert report.metric.value == 1, report.metric
        else:
            assert report.metric.status == "not_run" and report.metric.value is None
        reports.append({"case": name, "metric": report.metric.model_dump(mode="json"), "geometry": report.geometry,
            "seconds": report.seconds, "source_sha256": before, "source_unchanged": True,
            "root_kind": "staged" if root == ROOT else "existing_project", "report": f"{relative}/report.json",
            "role": "environment_only" if name == "official_t" else "fixture_or_existing_diagnostic"})
    source_camera = json.loads((ROOT/"fixtures/p1/procedural/source_index.json").read_text(encoding="utf-8"))["camera"]
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader"], capture_output=True, text=True)
        gpu_snapshot = gpu.stdout.strip() if gpu.returncode == 0 else "no_gpu_observation_exit_"+str(gpu.returncode)
    except FileNotFoundError:
        gpu_snapshot = "nvidia_smi_unavailable"
    summary = {"kind": "cpu_measurement_validation", "python": platform.python_version(), "platform": platform.system(),
        "runtime": {name: importlib.metadata.version(name) for name in ("numpy","trimesh","Pillow","pydantic","pytest")},
        "cases": reports, "source_fixture_camera": source_camera,
        "backend_mapping_status": "unverified_requires_development_calibration",
        "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"], "torch_imported": "torch" in sys.modules,
        "model_generated": False, "evaluation_executed": False, "holdout_executed": False,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "seconds": time.perf_counter()-started,
        "gpu_at_end": gpu_snapshot}
    assert not summary["torch_imported"]
    (results/"validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
