"""P0外层超时与独立Trimesh读取检查；用probe环境运行。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import trimesh


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for name in ("hamburger", "robot"):
        folder = args.output.resolve() / name
        folder.mkdir(parents=True, exist_ok=True)
        cmd = [str(root / "runtime/envs/reconstruction/Scripts/python.exe"),
               str(root / "scripts/p0/reconstruct_case.py"), "--root", str(root),
               "--image", str(root / "fixtures/p0" / (name + ".png")),
               "--output", str(folder)]
        started = time.perf_counter()
        with (folder / "process.log").open("w", encoding="utf-8") as stream:
            try:
                process = subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT,
                                         timeout=300, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                returncode = process.returncode
            except subprocess.TimeoutExpired:
                returncode = 124
        result = {"case": name, "command": cmd, "returncode": returncode,
                  "process_seconds": time.perf_counter() - started}
        if returncode == 0:
            result.update(json.loads((folder / "reconstruction.json").read_text(encoding="utf-8")))
            mesh = trimesh.load(folder / "raw_mesh.glb", force="mesh", process=False)
            valid = (len(mesh.vertices) > 0 and len(mesh.faces) > 0
                     and bool(np.isfinite(mesh.vertices).all())
                     and bool((mesh.faces >= 0).all())
                     and bool((mesh.faces < len(mesh.vertices)).all())
                     and bool((np.ptp(mesh.vertices, axis=0) > 0).all()))
            result["independent_read"] = {"valid": valid, "vertices": len(mesh.vertices),
                                           "faces": len(mesh.faces), "extents": mesh.extents.tolist(),
                                           "watertight": bool(mesh.is_watertight),
                                           "coordinates_unit": "model_unit_not_mm"}
            result["pass"] = valid and result["model_device"] == "cuda:0" and result["scene_code_device"] == "cuda:0"
        else:
            result["pass"] = False
        (folder / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        results.append(result)
        if not result["pass"]:
            break  # 先记录失败，再决定最小调整；不自动重试或切换设备。
    summary = {"cases": results, "pass": len(results) == 2 and all(r["pass"] for r in results)}
    (args.output / "reconstruction_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if not summary["pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
