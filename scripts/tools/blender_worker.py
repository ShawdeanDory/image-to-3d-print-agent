"""固定LinuxBlender后台：打印检测及受控简化；不用GPU。"""
import argparse,importlib.util,json,math
from pathlib import Path
import sys
import bpy,bmesh
from mathutils import Vector

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--operation',choices=['inspect','simplify','preview'],required=True)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--addon-dir',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    data=json.loads(args.input.read_text());parameters=data['parameters']
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    mesh=bpy.data.meshes.new('task_mesh')
    factor=.001 if parameters.get('unit')=='mm' else 1.
    mesh.from_pydata([[v*factor for v in row] for row in data['vertices']],[],data['faces']);mesh.update()
    obj=bpy.data.objects.new('task_mesh',mesh);bpy.context.collection.objects.link(obj)
    obj.select_set(True);bpy.context.view_layer.objects.active=obj
    spec=importlib.util.spec_from_file_location('fixed_print_helpers',args.addon_dir/'object_print3d_utils/mesh_helpers.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    result={'operation':args.operation,'blender_version':'.'.join(map(str,bpy.app.version)), 'blender_build':bpy.app.build_hash.decode(), 'toolbox_revision':'b42d68627734cb18af0e6f41537063984313a284','gpu_used':False}
    if args.operation=='inspect':
        solid=bmesh.new();solid.from_mesh(mesh);solid.normal_update()
        result['solid_crosscheck']={'non_manifold_edges_including_boundary':sum(not edge.is_manifold for edge in solid.edges),
            'inconsistent_contiguous_edges':sum(edge.is_manifold and not edge.is_contiguous for edge in solid.edges),
            'non_manifold_vertices_including_boundary':sum(not vertex.is_manifold for vertex in solid.verts)}
        solid.free()
        result['self_intersection_faces']=sorted(helper.bmesh_check_self_intersect_object(obj))
        if parameters['unit']=='mm':
            result['thin_faces_low']=sorted(helper.bmesh_check_thick_object(obj,(parameters['min_wall_mm']-.02)*.001))
            result['thin_faces_high']=sorted(helper.bmesh_check_thick_object(obj,(parameters['min_wall_mm']+.02)*.001))
        else:result.update(thin_faces_low=[],thin_faces_high=[])
        down=Vector((0,0,-1));overhang=[];critical=[]
        for face in mesh.polygons:
            angle=math.degrees(face.normal.angle(down,math.pi))
            bed=parameters['unit']=='mm' and all(abs(mesh.vertices[i].co.z)<=.00001 for i in face.vertices)
            if not bed:
                if angle<45-1e-5:overhang.append(face.index)
                elif abs(angle-45)<=1e-5:critical.append(face.index)
        result.update(overhang_faces=overhang,critical_overhang_faces=critical)
    elif args.operation=='simplify':
        modifier=obj.modifiers.new('confirmed_decimation','DECIMATE');modifier.ratio=parameters['target_faces']/len(mesh.polygons)
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        triangulate=obj.modifiers.new('triangulate','TRIANGULATE');bpy.ops.object.modifier_apply(modifier=triangulate.name)
        result.update(vertices=[[v/factor for v in vertex.co] for vertex in obj.data.vertices],faces=[list(face.vertices) for face in obj.data.polygons])
    else:
        scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=8
        scene.render.resolution_x=512;scene.render.resolution_y=512;scene.render.resolution_percentage=100
        scene.render.image_settings.file_format='PNG'
        low=Vector(tuple(min(v.co[i] for v in mesh.vertices) for i in range(3)))
        high=Vector(tuple(max(v.co[i] for v in mesh.vertices) for i in range(3)))
        center=(low+high)/2;span=max(high-low)
        material=bpy.data.materials.new('diagnostic_blue');material.diffuse_color=(.16,.42,.56,1.);obj.data.materials.append(material)
        bpy.ops.object.camera_add(location=center+Vector((1.8,-2.5,1.8))*span)
        camera=bpy.context.object;camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.type='ORTHO';camera.data.ortho_scale=span*1.6;scene.camera=camera
        for offset in [(2,-3,4),(-3,-1,2)]:
            bpy.ops.object.light_add(type='AREA',location=center+Vector(offset)*span)
            lamp=bpy.context.object;lamp.data.energy=max(1.,span*span*300);lamp.data.shape='DISK';lamp.data.size=span*3
            lamp.rotation_euler=(center-lamp.location).to_track_quat('-Z','Y').to_euler()
        scene.world.color=(.4,.4,.4);scene.render.filepath=str(args.output.parent/'preview.png')
        bpy.ops.render.render(write_still=True)
        result.update(preview_file='preview.png',render_device='CPU',material_override='diagnostic_blue')
    args.output.write_text(json.dumps(result,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'operation':args.operation,'status':'completed','blender':bpy.app.version_string}))

if __name__=='__main__':main()
