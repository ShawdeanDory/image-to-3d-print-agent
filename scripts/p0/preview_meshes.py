"""将P0原始重建网格渲染为人工核对图片，不修复或定标。"""
import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


parser = argparse.ArgumentParser()
parser.add_argument("--input", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = 640
scene.render.resolution_y = 480
scene.render.resolution_percentage = 100
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "SINGLE"
scene.display.shading.single_color = (.15, .55, .8)
scene.display.shading.show_cavity = True

for name in ("hamburger", "robot"):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    folder = args.input.resolve() / name
    bpy.ops.import_scene.gltf(filepath=str(folder / "raw_mesh.glb"))
    # 上游TripoSR是Z朝上；只在临时预览场景撤销glTF导入的轴转换，不改写原始文件。
    inverse_gltf_axis = Matrix.Rotation(-math.pi / 2, 4, "X")
    for obj in list(scene.objects):
        if obj.type == "MESH":
            obj.matrix_world = inverse_gltf_axis @ obj.matrix_world
    points = [obj.matrix_world @ Vector(v) for obj in scene.objects
              if obj.type == "MESH" for v in obj.bound_box]
    if not points:
        raise RuntimeError("导入后没有可预览的网格")
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (low + high) / 2
    span = max(high - low)
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = span * 1.8
    scene.camera = camera
    for filename, direction in (("preview.png", (2.5, -1.5, 1.3)),
                                ("preview_reverse.png", (-2.5, 1.5, 1.3))):
        camera.location = center + Vector(direction) * span
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(folder / filename)
        bpy.ops.render.render(write_still=True)
