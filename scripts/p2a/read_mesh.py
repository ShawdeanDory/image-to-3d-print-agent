"""在独立probe环境检查原始网格；不据此判定可打印。"""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import numpy as np
    import trimesh
    mesh = trimesh.load(args.mesh, force="mesh", process=False)
    assert len(mesh.vertices) > 0 and len(mesh.faces) > 0
    assert np.isfinite(mesh.vertices).all()
    assert mesh.faces.min() >= 0 and mesh.faces.max() < len(mesh.vertices)
    report = {"kind": "independent_raw_mesh_read", "path": str(args.mesh),
              "vertices": int(len(mesh.vertices)), "faces": int(len(mesh.faces)),
              "finite_coordinates": True, "valid_indices": True,
              "watertight": bool(mesh.is_watertight),
              "trimesh": trimesh.__version__, "printability": "not_evaluated"}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
