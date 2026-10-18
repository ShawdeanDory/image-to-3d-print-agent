"""P0独立STL读取与虚拟FDM配置切片验证，不控制实际打印机。"""
import argparse
import json
from pathlib import Path
import subprocess
import time

import numpy as np
import trimesh


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / "geometry/cube_10mm.stl"
    mesh = trimesh.load(source, force="mesh", process=False)
    independent = {"reader": "Trimesh", "coordinates_unit": "mm",
                   "dimensions_mm": mesh.extents.tolist(), "volume_mm3": float(mesh.volume),
                   "finite": bool(np.isfinite(mesh.vertices).all())}
    independent["pass"] = bool(independent["finite"] and np.all(np.abs(mesh.extents - 10) <= .01)
                                and abs(mesh.volume - 1000) <= 1)
    command = [str(root / "runtime/tools/prusaslicer/PrusaSlicer-2.9.6/prusa-slicer-console.exe"),
               "--datadir", str(root / "runtime/cache/prusaslicer"),
               "--load", str(root / "fixtures/p0/demo_fdm_pla.ini"),
               "--config-compatibility", "disable", "--export-gcode", "--output",
               str((args.output / "cube_10mm.gcode").resolve()), str(source.resolve())]
    started = time.perf_counter()
    with (args.output / "slice_verified.log").open("w", encoding="utf-8") as stream:
        try:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            returncode = 124
    summary = {"command": command, "returncode": returncode,
               "seconds": time.perf_counter() - started, "physical_print": False,
               "profile": "demo_fdm_pla", "independent_stl_read": independent}
    if returncode == 0:
        path = args.output / "cube_10mm.gcode"
        content = path.read_text(encoding="utf-8")
        heights = [float(line.split(":", 1)[1]) for line in content.splitlines() if line.startswith(";Z:")]
        extrusion = any(line.startswith("G1 ") and " E" in line for line in content.splitlines())
        summary.update(bytes=path.stat().st_size, layers=content.count(";LAYER_CHANGE"),
                       layer_z_mm=heights, has_extrusion_moves=extrusion)
        summary["pass"] = (independent["pass"] and len(heights) == 50 and
                           abs(heights[-1] - 10) <= .01 and extrusion)
    else:
        summary["pass"] = False
    (args.output / "slice_verified.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if not summary["pass"]:
        raise RuntimeError("P0切片或独立STL读取未达到预期")


if __name__ == "__main__":
    main()
