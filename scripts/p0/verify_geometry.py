"""P0固定几何样例验证；由便携Blender后台运行，不是业务模块。"""
import argparse
import json
import math
import random
import subprocess
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.addon_dir.resolve()))
    import object_print3d_utils
    from object_print3d_utils import operators
    object_print3d_utils.register()
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.print_3d.thickness_min = 0.0012

    def reset():
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

    def cube(name, dimensions, center=(0, 0, 0)):
        bpy.ops.mesh.primitive_cube_add(size=1, location=center)
        obj = bpy.context.object
        obj.name = name
        obj.dimensions = dimensions
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        return obj

    def checks(obj):
        info = []
        random.seed(0)
        for checker in (operators.MESH_OT_print3d_check_solid,
                        operators.MESH_OT_print3d_check_intersections,
                        operators.MESH_OT_print3d_check_thick):
            checker.main_check(obj, info)
        return {label.rsplit(":", 1)[0]: len(data[1]) for label, data in info}

    def export(obj, name):
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        path = args.output / (name + ".stl")
        bpy.ops.wm.stl_export(filepath=str(path.resolve()), export_selected_objects=True,
                              global_scale=1000.0, use_scene_unit=False)
        return path

    def preview(obj, name):
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x = 640
        scene.render.resolution_y = 480
        scene.render.resolution_percentage = 100
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "SINGLE"
        scene.display.shading.single_color = (0.15, 0.55, 0.8)
        scene.display.shading.show_cavity = True
        center = sum((obj.matrix_world @ Vector(v) for v in obj.bound_box), Vector()) / 8
        span = max(obj.dimensions)
        bpy.ops.object.camera_add(location=center + Vector((1.8, -2.5, 1.8)) * span)
        camera = bpy.context.object
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = span * 1.8
        scene.camera = camera
        scene.render.filepath = str((args.output / (name + ".png")).resolve())
        bpy.ops.render.render(write_still=True)

    reset()
    obj = cube("cube_10mm", (.01, .01, .01), (0, 0, .005))
    cube_path = export(obj, "cube_10mm")
    reset()
    bpy.ops.wm.stl_import(filepath=str(cube_path.resolve()), global_scale=.001,
                          use_scene_unit=False)
    obj = bpy.context.object
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    dimensions = [float(v * 1000) for v in obj.dimensions]
    volume = float(abs(bm.calc_volume()) * 1e9)
    bm.free()
    cube_checks = checks(obj)
    result = {
        "blender_version": bpy.app.version_string,
        "addon_version": object_print3d_utils.bl_info.get("version"),
        "addon_commit": subprocess.check_output(
            ["git", "-C", str(args.addon_dir), "rev-parse", "HEAD"], text=True).strip(),
        "units": {"internal": "m", "stl_coordinates": "mm", "thickness_min_mm": 1.2},
        "cube": {"dimensions_mm": dimensions, "volume_mm3": volume, "checks": cube_checks},
    }
    result["cube"]["pass"] = (max(abs(v - 10) for v in dimensions) <= .01
                                   and abs(volume - 1000) <= 1
                                   and all(v == 0 for v in cube_checks.values()))
    preview(obj, "cube_10mm")

    reset()
    obj = cube("thin_wall_0p9mm", (.02, .02, .0009), (0, 0, .00045))
    export(obj, obj.name)
    thin_checks = checks(obj)
    result["thin_wall"] = {"thickness_mm": .9, "checks": thin_checks,
                           "pass": thin_checks["Thin Faces"] > 0}
    preview(obj, "thin_wall_0p9mm")

    reset()
    first = cube("overlap_a", (.01, .01, .01))
    second = cube("overlap_b", (.01, .01, .01), (.004, .003, .002))
    first.select_set(True)
    second.select_set(True)
    bpy.context.view_layer.objects.active = first
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = "self_intersection"
    export(obj, obj.name)
    overlap_checks = checks(obj)
    result["self_intersection"] = {"construction": "two_closed_overlapping_cubes_without_boolean_union",
                                    "checks": overlap_checks,
                                    "pass": overlap_checks["Intersect Face"] > 0}
    preview(obj, obj.name)
    result["pass"] = all(result[key]["pass"] for key in ("cube", "thin_wall", "self_intersection"))
    (args.output / "geometry.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if not result["pass"]:
        raise RuntimeError("P0固定几何样例与预期不一致，见geometry.json")


if __name__ == "__main__":
    main()
