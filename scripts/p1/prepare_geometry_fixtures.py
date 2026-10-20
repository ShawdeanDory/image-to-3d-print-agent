"""准备解析几何fixture，不运行检查器、修复或模型。"""
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "fixtures/p1/geometry"
VERTICES = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
            (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
FACES = [(1, 3, 2), (1, 4, 3), (5, 6, 7), (5, 7, 8),
         (1, 2, 6), (1, 6, 5), (4, 8, 7), (4, 7, 3),
         (1, 5, 8), (1, 8, 4), (2, 3, 7), (2, 7, 6)]


def write_obj(name, vertices, faces, expected):
    lines = ["# P1解析fixture；单位毫米；未执行打印检查"]
    lines += ["v " + " ".join(map(str, vertex)) for vertex in vertices]
    lines += ["f " + " ".join(map(str, face)) for face in faces]
    (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"file": name, "source": "scripts/p1/prepare_geometry_fixtures.py@1.0.0",
            "expected": expected, "verification": "P1仅准备，工具检查待P3"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for name, expected in [
        ("cube_10mm.stl", "尺寸10×10×10毫米，正常拓扑"),
        ("thin_wall_0p9mm.stl", "1.2毫米阈值下检出薄壁"),
        ("self_intersection.stl", "检出相交面，不能用水密替代"),
    ]:
        target = OUT / name
        # 交接时入库文件已存在；首次准备才从既有P0运行目录复制。
        if not target.is_file():
            shutil.copyfile(ROOT / "runs/p0/p0-20261018-01/geometry" / name, target)
        records.append({"file": name, "source": "scripts/p0/verify_geometry.py@3acd937",
                        "expected": expected, "verification": "P0已实测；P1不重跑检查"})
    box = [(x * 10, y * 10, z * 10) for x, y, z in VERTICES]
    records.append(write_obj("open_cube.obj", box, FACES[:-2], "存在开口边界"))
    records.append(write_obj("reversed_face.obj", box, [FACES[0][::-1], *FACES[1:]], "存在反向面"))
    records.append(write_obj("duplicate_face.obj", box, [*FACES, FACES[0]], "重复面及非流形边"))
    for thickness in [0.6, 1.2, 1.6]:
        name = "wall_1p6mm.obj" if thickness == 1.6 else "thin_wall_" + str(thickness).replace(".", "p") + "mm.obj"
        vertices = [(x * thickness, y * 10, z * 10) for x, y, z in VERTICES]
        expected = "已知厚度" + str(thickness) + "毫米；1.2毫米临界项需复核"
        records.append(write_obj(name, vertices, FACES, expected))
    records.append(write_obj("slanted_face.obj", [(0, 0, 0), (10, 0, 10), (0, 10, 0)],
                             [(1, 3, 2)], "向下45度临界斜面，核对角度定义"))
    second = [(x + 20, y, z) for x, y, z in box]
    records.append(write_obj("multiple_components.obj", box + second,
                             FACES + [tuple(i + 8 for i in face) for face in FACES], "两个分离闭合组件"))
    # 两个四面体只共享顶点1，所有边各邻接两面，但该顶点的邻域不成单个环。
    vertices = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10),
                (-10, 0, 0), (0, -10, 0), (0, 0, -10)]
    faces = [(1, 3, 2), (1, 2, 4), (2, 3, 4), (3, 1, 4),
             (1, 5, 6), (1, 7, 5), (5, 7, 6), (6, 7, 1)]
    records.append(write_obj("non_manifold_vertex.obj", vertices, faces, "仅共享一点的非流形顶点"))
    (OUT / "manifest.json").write_text(json.dumps({"version": "1.0.0", "unit": "mm",
        "license": "CC0-1.0", "fixtures": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("几何fixture已准备：", len(records))


if __name__ == "__main__":
    main()
