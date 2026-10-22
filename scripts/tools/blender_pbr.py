"""Blender内部使用：在最终网格上重烘焙官方PBR，不改变顶点或三角面。"""
import math
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix


def bake_pbr(target,parameters,directory):
    directory=Path(directory);size=int(parameters['texture_size'])
    before=set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=parameters['source_glb'])
    sources=[o for o in bpy.data.objects if o not in before and o.type=='MESH']
    if not sources:raise ValueError('原始PBR没有网格')
    # glTF导入器已将Y朝上变为Blender的Z朝上；原生Z朝上的文件撤销这一步。
    correction=Matrix.Identity(4) if parameters['source_frame']=='y_up' else Matrix.Rotation(-math.pi/2,4,'X')
    transform=Matrix.Diagonal((.001,.001,.001,1.))@Matrix(parameters['source_to_mm'])@correction
    original_world={source:source.matrix_world.copy() for source in sources}
    for source in sources:source.matrix_world=transform@original_world[source]
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT');target.select_set(True);bpy.context.view_layer.objects.active=target
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66),island_margin=.015,scale_to_bounds=True)
    bpy.ops.object.mode_set(mode='OBJECT')
    for face in target.data.polygons:face.use_smooth=True
    material=bpy.data.materials.new('processed_official_pbr');material.use_nodes=True
    target.data.materials.clear();target.data.materials.append(material)
    nodes=material.node_tree.nodes;links=material.node_tree.links
    output=nodes.get('Material Output');principled=nodes.get('Principled BSDF')
    bake_node=nodes.new('ShaderNodeTexImage');nodes.active=bake_node;bake_node.select=True
    emission=nodes.new('ShaderNodeEmission')
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=1
    scene.render.bake.margin=8
    span=max(target.dimensions);distance=max(span*.02,1e-6)
    source_materials={m for o in sources for m in o.data.materials if m is not None}
    rewires=[]
    for mat in source_materials:
        if not mat.use_nodes:raise ValueError('原PBR材质没有节点')
        tree=mat.node_tree;shader=next((n for n in tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
        out=next((n for n in tree.nodes if n.type=='OUTPUT_MATERIAL' and n.is_active_output),None)
        if shader is None or out is None:raise ValueError('原PBR材质缺Principled或输出节点')
        previous=[(link.from_socket,link.to_socket) for link in out.inputs['Surface'].links]
        emit=tree.nodes.new('ShaderNodeEmission');rewires.append((tree,shader,out,emit,previous))

    def image(name,color=False):
        item=bpy.data.images.new('pbr_'+name,width=size,height=size,alpha=True)
        item.generated_color=(0,0,0,0);item.colorspace_settings.name='sRGB' if color else 'Non-Color'
        return item

    def select_sources(enabled):
        bpy.ops.object.select_all(action='DESELECT')
        for obj in sources:obj.select_set(enabled)
        target.select_set(True);bpy.context.view_layer.objects.active=target

    def bake(name,channel=None,own=False):
        item=image(name,color=name=='base_color');bake_node.image=item;nodes.active=bake_node
        select_sources(not own)
        if own:
            links.new(emission.outputs['Emission'],output.inputs['Surface']);emission.inputs['Color'].default_value=(1,1,1,1)
        else:
            for tree,shader,out,emit,previous in rewires:
                for link in list(emit.inputs['Color'].links):tree.links.remove(link)
                if channel:
                    socket=shader.inputs[channel]
                    if socket.is_linked:tree.links.new(socket.links[0].from_socket,emit.inputs['Color'])
                    else:
                        value=socket.default_value
                        emit.inputs['Color'].default_value=tuple(value) if hasattr(value,'__len__') else (value,value,value,1.)
                else:emit.inputs['Color'].default_value=(1,1,1,1)
                tree.links.new(emit.outputs['Emission'],out.inputs['Surface'])
        bpy.ops.object.bake(type='EMIT',use_selected_to_active=not own,use_clear=True,
            cage_extrusion=distance*.5,max_ray_distance=distance,margin=0 if name in {'mask','coverage'} else 8)
        return item

    def pixels(item):
        values=np.empty(size*size*4,dtype=np.float32);item.pixels.foreach_get(values)
        return values.reshape(-1,4)

    footprint=bake('mask',own=True);covered=bake('coverage')
    mask=pixels(footprint)[:,0]>.5;hits=pixels(covered)[:,0]>.5
    coverage=float((mask&hits).sum()/max(int(mask.sum()),1))
    if not mask.any() or coverage<.99:raise ValueError(f'官方纹理投射覆盖率{coverage:.2%}不足99%')
    maps={name:bake(name,channel) for name,channel in
        [('base_color','Base Color'),('roughness','Roughness'),('metallic','Metallic')]}
    for tree,shader,out,emit,previous in rewires:
        for link in list(out.inputs['Surface'].links):tree.links.remove(link)
        for source,destination in previous:tree.links.new(source,destination)
    normal=image('normal');bake_node.image=normal;nodes.active=bake_node;select_sources(True)
    bpy.ops.object.bake(type='NORMAL',normal_space='TANGENT',use_selected_to_active=True,use_clear=True,
        cage_extrusion=distance*.5,max_ray_distance=distance,margin=8)
    packed=image('metallic_roughness');rgba=np.ones((size*size,4),dtype=np.float32)
    rgba[:,1]=pixels(maps['roughness'])[:,0];rgba[:,2]=pixels(maps['metallic'])[:,0]
    packed.pixels.foreach_set(rgba.ravel());packed.update()
    links.new(principled.outputs['BSDF'],output.inputs['Surface'])
    for item in [maps['base_color'],packed,normal]:
        item.filepath_raw=str(directory/(item.name+'.png'));item.file_format='PNG';item.save();item.pack()
    color_node=nodes.new('ShaderNodeTexImage');color_node.image=maps['base_color']
    links.new(color_node.outputs['Color'],principled.inputs['Base Color'])
    mr_node=nodes.new('ShaderNodeTexImage');mr_node.image=packed
    separate=nodes.new('ShaderNodeSeparateColor');separate.mode='RGB';links.new(mr_node.outputs['Color'],separate.inputs['Color'])
    links.new(separate.outputs['Green'],principled.inputs['Roughness']);links.new(separate.outputs['Blue'],principled.inputs['Metallic'])
    normal_node=nodes.new('ShaderNodeTexImage');normal_node.image=normal
    tangent=nodes.new('ShaderNodeNormalMap');links.new(normal_node.outputs['Color'],tangent.inputs['Color'])
    links.new(tangent.outputs['Normal'],principled.inputs['Normal'])
    select_sources(False)
    bpy.ops.export_scene.gltf(filepath=str(directory/'pbr-model.glb'),export_format='GLB',use_selection=True,
        export_yup=True,export_materials='EXPORT',export_texcoords=True,export_normals=True,export_tangents=True)
    return {'pbr_file':'pbr-model.glb','coverage':coverage,'texture_size':size,
        'channels':['base_color','roughness','metallic','normal'],'geometry_modified':False,
        'method':'selected_to_active_cpu','alpha_mode':'OPAQUE','render_device':'CPU'}
