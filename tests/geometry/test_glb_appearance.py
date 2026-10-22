"""处理顶点底色GLB的材质和颜色口径，不运行生成模型。"""
import json
import struct
import numpy as np
import trimesh
from image_to_3d_print.geometry.core import load_mesh


def parse_glb(data):
    length,_=struct.unpack_from('<II',data,12)
    return json.loads(data[20:20+length]),data[28+length:]


def test_processed_glb_matches_ply_material_and_linear_color(tmp_path):
    from image_to_3d_print.geometry.appearance import export_base_color_glb
    mesh=trimesh.creation.box()
    colors=np.tile([128,192,32,255],(len(mesh.vertices),1)).astype(np.uint8)
    mesh.visual.vertex_colors=colors
    before=mesh.vertices.copy();faces=mesh.faces.copy()
    data=export_base_color_glb(mesh);tree,buffer=parse_glb(data)
    primitive=tree['meshes'][0]['primitives'][0]
    material=tree['materials'][primitive['material']]
    assert material['pbrMetallicRoughness']['metallicFactor']==0
    assert material['pbrMetallicRoughness']['roughnessFactor']==.85
    assert 'NORMAL' in primitive['attributes']
    accessor=tree['accessors'][primitive['attributes']['COLOR_0']]
    assert accessor['componentType']==5126
    view=tree['bufferViews'][accessor['bufferView']]
    actual=np.frombuffer(buffer,dtype='<f4',count=len(mesh.vertices)*4,offset=view.get('byteOffset',0)).reshape(-1,4)
    srgb=colors[:,:3]/255.
    expected=np.where(srgb<=.04045,srgb/12.92,((srgb+.055)/1.055)**2.4)
    assert np.allclose(actual[:,:3],expected,atol=1e-7)
    assert np.all(actual[:,3]==1)
    assert np.array_equal(mesh.vertices,before) and np.array_equal(mesh.faces,faces)
    assert np.array_equal(mesh.visual.vertex_colors,colors)
    file=tmp_path/'fixed.glb';file.write_bytes(data);read=load_mesh(file)
    assert np.allclose(read.extents,mesh.extents)


def test_existing_texture_material_is_not_overridden():
    from image_to_3d_print.geometry.appearance import export_base_color_glb
    from PIL import Image
    mesh=trimesh.creation.box()
    mesh.visual=trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices),2)),
        material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new('RGB',(2,2),'yellow'),metallicFactor=.4,roughnessFactor=.2))
    tree,_=parse_glb(export_base_color_glb(mesh))
    material=tree['materials'][0]['pbrMetallicRoughness']
    assert material['metallicFactor']==.4 and material['roughnessFactor']==.2
    assert 'baseColorTexture' in material
