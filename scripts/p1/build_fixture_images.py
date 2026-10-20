"""用已安装Blender的Cycles CPU生成受控输入图片；不运行神经模型。"""
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

root = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
out = root / "fixtures/p1/procedural"
out.mkdir(parents=True, exist_ok=True)
# 每个名字表示不同对象结构；共享基本几何不代表同一对象。
recipes = {
    "block": [("cube", (0,0,0), (.7,.5,.9))],
    "pyramid": [("pyramid", (0,0,0), (.8,.8,.9))],
    "bead": [("sphere", (0,0,0), (.8,.8,.8))],
    "knob": [("cylinder", (0,0,-.3), (.6,.6,.4)), ("sphere", (0,0,.4), (.5,.5,.5))],
    "cone": [("cone", (0,0,0), (.7,.7,.9))],
    "octahedron": [("octahedron", (0,0,0), (.8,.8,.8))],
    "ring": [("torus", (0,0,0), (.8,.8,.8))],
    "stairs": [("cube",(-.6,0,-.4),(.3,.6,.2)),("cube",(0,0,-.2),(.3,.6,.4)),("cube",(.6,0,0),(.3,.6,.6))],
    "tower": [("cylinder",(0,0,-.3),(.5,.5,.6)),("cone",(0,0,.65),(.7,.7,.4))],
    "mushroom": [("cylinder",(0,0,-.4),(.25,.25,.5)),("sphere",(0,0,.25),(.8,.8,.35))],
    "arch": [("cube",(-.6,0,0),(.2,.4,.8)),("cube",(.6,0,0),(.2,.4,.8)),("cube",(0,0,.7),(.8,.4,.2))],
    "cross": [("cube",(0,0,0),(.25,.25,.9)),("cube",(0,0,.3),(.8,.25,.25))],
    "spool": [("cylinder",(0,0,0),(.3,.3,.7)),("cylinder",(0,0,-.65),(.7,.7,.12)),("cylinder",(0,0,.65),(.7,.7,.12))],
    "trophy": [("cylinder",(0,0,-.65),(.5,.5,.1)),("cylinder",(0,0,-.25),(.17,.17,.4)),("sphere",(0,0,.5),(.6,.6,.6))],
    "pedestal": [("cube",(0,0,-.5),(.7,.7,.2)),("cube",(0,0,0),(.3,.3,.4)),("cube",(0,0,.5),(.6,.6,.15))],
    "toy_house": [("cube",(0,0,-.2),(.65,.6,.6)),("pyramid",(0,0,.65),(.9,.85,.35))],
}
index=[]
for name,recipe in recipes.items():
    bpy.ops.object.select_all(action="SELECT");bpy.ops.object.delete(use_global=False)
    scene=bpy.context.scene
    scene.render.engine="CYCLES";scene.cycles.device="CPU";scene.cycles.samples=8;scene.cycles.seed=0
    scene.render.resolution_x=256;scene.render.resolution_y=256;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format="PNG";scene.render.image_settings.color_mode="RGBA";scene.render.film_transparent=True
    mat=bpy.data.materials.new("fixture_material");mat.diffuse_color=(.22,.48,.68,1)
    for kind,loc,scale in recipe:
        if kind=="cube":bpy.ops.mesh.primitive_cube_add(size=2,location=loc)
        elif kind=="sphere":bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=12,location=loc)
        elif kind=="cylinder":bpy.ops.mesh.primitive_cylinder_add(vertices=32,depth=2,location=loc)
        elif kind in {"cone","pyramid"}:bpy.ops.mesh.primitive_cone_add(vertices=4 if kind=="pyramid" else 32,radius1=1,radius2=0,depth=2,location=loc)
        elif kind=="octahedron":
            mesh = bpy.data.meshes.new("octahedron")
            mesh.from_pydata([(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)], [],
                [(0,2,4),(2,1,4),(1,3,4),(3,0,4),(2,0,5),(1,2,5),(3,1,5),(0,3,5)])
            mesh.update()
            obj = bpy.data.objects.new("octahedron", mesh)
            bpy.context.collection.objects.link(obj)
            bpy.context.view_layer.objects.active = obj
            obj.location = loc
        else:bpy.ops.mesh.primitive_torus_add(major_radius=.7,minor_radius=.23,location=loc)
        obj=bpy.context.view_layer.objects.active;obj.scale=scale;obj.data.materials.append(mat)
    bpy.ops.object.camera_add(location=(3,-4,3))
    camera=bpy.context.object;camera.rotation_euler=(Vector((0,0,0))-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.type="ORTHO";camera.data.ortho_scale=3.6;scene.camera=camera
    bpy.ops.object.light_add(type="AREA",location=(2,-3,5));bpy.context.object.data.energy=500;bpy.context.object.data.shape="DISK";bpy.context.object.data.size=4
    scene.world.color=(.35,.35,.35)
    scene.render.filepath=str(out/(name+".png"));bpy.ops.render.render(write_still=True)
    index.append({"object_group":"procedural_"+name,"image":name+".png","recipe":recipe})
(out/"source_index.json").write_text(json.dumps({"generator_version":"1.0.0","blender":bpy.app.version_string,"engine":"CYCLES","device":"CPU","seed":0,"samples":8,"camera":{"location":[3,-4,3],"target":[0,0,0],"orthographic_scale":3.6},"license":"CC0-1.0","objects":index},ensure_ascii=False,indent=2),encoding="utf-8")
print("P1_CPU_FIXTURES_READY",len(index),flush=True)
