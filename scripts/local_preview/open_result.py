"""在新的Blender场景导入原始GLB，只调整预览坐标，不改写文件。"""
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix


mesh_path, ready_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=str(mesh_path))
meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
if not meshes:
    raise RuntimeError("GLB导入后没有网格")
# TripoSR原始坐标Z朝上，撤销glTF导入的轴转换，只作用于本次查看。
for obj in meshes:
    obj.matrix_world = Matrix.Rotation(-math.pi / 2, 4, "X") @ obj.matrix_world
bpy.context.view_layer.update()
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            region = next(region for region in area.regions if region.type == "WINDOW")
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.view3d.view_all(center=True)
            area.spaces.active.shading.type = "MATERIAL"
result = {"mesh": str(mesh_path), "mesh_objects": len(meshes),
          "vertices": sum(len(obj.data.vertices) for obj in meshes),
          "faces": sum(len(obj.data.polygons) for obj in meshes),
          "blender": bpy.app.version_string, "preview_only_axis_transform": True}
pending = ready_path.with_suffix(".tmp")
pending.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
pending.replace(ready_path)
print(json.dumps(result, ensure_ascii=False), flush=True)
