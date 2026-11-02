"""固定纹理/几何，不调用模型或重烘焙。"""
import numpy as np
import pytest
import trimesh
from PIL import Image
from image_to_3d_print.geometry.glb_preserve import GLBDocument,write_plain_glb
from image_to_3d_print.geometry.core import load_mesh
from image_to_3d_print.artifacts.print_color import reproject_pbr
from image_to_3d_print.tools import digest,ToolFailure


def textured(tmp_path):
    mesh=trimesh.creation.box(extents=[20,25,120])
    mesh.visual=trimesh.visual.TextureVisuals(uv=np.tile([[.1,.1],[.8,.1],[.8,.9],[.1,.9]],(2,1)),
        material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new('RGB',(8,8),(30,140,220)),metallicFactor=.1,roughnessFactor=.6))
    file=tmp_path/'source.glb';file.write_bytes(trimesh.exchange.gltf.export_glb(mesh,include_normals=True))
    return file,mesh


def test_reprojection_retains_source_textures_and_final_geometry(tmp_path):
    source,mesh=textured(tmp_path);before=digest(source);target=mesh.copy();target.vertices[:,0]*=1.01
    output=tmp_path/'final.glb';facts=reproject_pbr(source,target,output)
    final=GLBDocument(output)
    assert final.has_uv and final.material_signature()==GLBDocument(source).material_signature()
    assert digest(source)==before and facts['rebaked'] is False and facts['approximation'] is True
    np.testing.assert_allclose(load_mesh(output).extents,target.extents,atol=.001)
    assert len(load_mesh(output).faces)==len(target.faces)


def test_missing_texture_is_explicit_and_not_fake_color(tmp_path):
    file=tmp_path/'plain.glb';mesh=trimesh.creation.box();write_plain_glb(mesh,file,'mm')
    with pytest.raises(ToolFailure,match='UV|贴图'):reproject_pbr(file,mesh,tmp_path/'output.glb')


def test_remote_geometry_is_rejected_instead_of_random_uv(tmp_path):
    file,mesh=textured(tmp_path);mesh.apply_translation([1000,0,0])
    with pytest.raises(ToolFailure,match='距离|对应'):reproject_pbr(file,mesh,tmp_path/'output.glb')


def test_source_and_existing_outputs_cannot_be_overwritten(tmp_path):
    file,mesh=textured(tmp_path);before=digest(file)
    with pytest.raises(ToolFailure,match='覆盖'):reproject_pbr(file,mesh,file)
    assert digest(file)==before


def test_multiple_material_groups_remain_separate(tmp_path):
    import copy
    file,mesh=textured(tmp_path);doc=GLBDocument(file);p=doc.primitives[0];faces=doc.faces(p)
    second=copy.deepcopy(doc.tree['materials'][0]);second['pbrMetallicRoughness']['baseColorFactor']=[.3,1.,.2,1.]
    doc.tree['materials'].append(second);parts=[]
    for i,group in enumerate(np.array_split(faces,2)):
        item=copy.deepcopy(p);item['material']=i;item['indices']=doc.append(group.reshape(-1,1),'SCALAR',5125);parts.append(item)
    doc.tree['meshes'][0]['primitives']=parts;source=tmp_path/'multi.glb';doc.save(source)
    out=tmp_path/'color.glb';reproject_pbr(source,mesh,out)
    final=GLBDocument(out)
    assert len(final.primitives)==2 and final.material_signature()==GLBDocument(source).material_signature()
    assert sum(len(final.faces(p)) for p in final.primitives)==len(mesh.faces)
