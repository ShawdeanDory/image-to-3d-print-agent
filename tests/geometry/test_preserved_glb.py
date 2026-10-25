from pathlib import Path
from uuid import uuid4
import numpy as np
import pytest
import trimesh
from PIL import Image
from image_to_3d_print.geometry.core import MeshStore,load_mesh,topology
from image_to_3d_print.geometry.glb_preserve import GLBDocument,prepare_inspection_glb,preserve_glb
from image_to_3d_print.schemas import ModelTaskRequest
from image_to_3d_print.tools import ToolFailure,digest


def textured(path):
    # 每面拆点形成UV接缝，拓扑检查仍应识别为封闭立方体。
    box=trimesh.creation.box()
    mesh=trimesh.Trimesh(vertices=box.vertices[box.faces].reshape(-1,3),faces=np.arange(36).reshape(-1,3),process=False)
    material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new('RGB',(8,8),(96,140,220)),metallicFactor=.7,roughnessFactor=.2)
    mesh.visual=trimesh.visual.TextureVisuals(uv=np.tile([[0.,0.],[1.,0.],[0.,1.]],(12,1)),material=material)
    path.write_bytes(trimesh.exchange.gltf.export_glb(mesh,include_normals=True))
    return path


def test_check_clean_scale_preserves_uv_pbr_without_ply(tmp_path):
    original=textured(tmp_path/'original.glb');before=digest(original)
    stats=prepare_inspection_glb(original,tmp_path/'input.glb','y_up')
    assert stats['face_count']==12 and stats['vertex_count']==36
    store=MeshStore(tmp_path);run=uuid4();raw=store.import_mesh('input.glb',run)
    assert topology(load_mesh(tmp_path/raw.relative_path))['watertight']
    clean=store.clean(run,raw.mesh_version,count_repair_round=False)
    assert clean.tool.succeeded
    request=ModelTaskRequest(image_asset_id='image',printer_profile_id='demo',height_value=100.,height_unit='mm',scale_source='user_target',orientation={'up_axis':'z','confirmed':True})
    scaled=store.scale(run,clean.tool.data['mesh_version'],request)
    assert scaled.tool.succeeded
    final=store.get(run,scaled.tool.data['mesh_version']);path=tmp_path/final.relative_path
    assert path.suffix=='.glb' and not list((tmp_path/'runs').rglob('*.ply'))
    assert load_mesh(path).extents[2]==pytest.approx(100.)
    a,b=GLBDocument(original),GLBDocument(path)
    assert a.material_signature()==b.material_signature()
    assert b.has_uv and len(b.positions)>len(load_mesh(path).vertices)
    assert digest(original)==before


def test_existing_copy_restoration_retains_each_uv_corner(tmp_path):
    source=textured(tmp_path/'source.glb');a=GLBDocument(source)
    mesh=load_mesh(source);mesh.update_faces(np.arange(len(mesh.faces))!=0)
    output=tmp_path/'copy.glb';facts=preserve_glb(source,mesh,output)
    b=GLBDocument(output)
    assert facts['retained_faces']==11 and facts['new_patch_faces']==0
    assert a.material_signature()==b.material_signature()
    source_uv=a.accessor(a.primitives[0]['attributes']['TEXCOORD_0'])
    target_uv=b.accessor(b.primitives[0]['attributes']['TEXCOORD_0'])
    assert set(map(tuple,target_uv))==set(map(tuple,source_uv))
    assert len(load_mesh(output).faces)==11


def test_new_patch_is_explicit_and_existing_material_is_unchanged(tmp_path):
    source=textured(tmp_path/'source.glb');mesh=load_mesh(source)
    mesh.faces=np.vstack([mesh.faces,[0,2,7]])
    facts=preserve_glb(source,mesh,tmp_path/'patch.glb',allow_new_faces=True)
    doc=GLBDocument(tmp_path/'patch.glb')
    assert facts['new_patch_faces']==1
    assert facts['untextured_patch_faces']==1 and facts['appearance']=='original_pbr_with_untextured_patches'
    assert doc.tree['materials'][0]==GLBDocument(source).tree['materials'][0]
    assert doc.primitives[-1]['extras']['appearance']=='untextured_patch'


def test_changed_vertices_cannot_silently_drop_pbr(tmp_path):
    source=textured(tmp_path/'source.glb');mesh=load_mesh(source)
    mesh.vertices[0]+=[.05,0,0]
    with pytest.raises(ToolFailure):preserve_glb(source,mesh,tmp_path/'bad.glb')
    assert not (tmp_path/'bad.glb').exists()


def test_multiple_material_primitives_keep_their_images(tmp_path):
    a=trimesh.load(textured(tmp_path/'a.glb'),force='mesh',process=False)
    b=a.copy();b.apply_translation([2,0,0])
    b.visual.material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new('RGB',(8,8),'red'),metallicFactor=.1)
    source=tmp_path/'scene.glb';source.write_bytes(trimesh.Scene([a,b]).export(file_type='glb'))
    # 多对象输入先明确拒绝，不能悄悄合并而丢材质；单对象多primitive由实现支持。
    with pytest.raises(ToolFailure):preserve_glb(source,load_mesh(source),tmp_path/'bad.glb')


def test_single_mesh_multiple_primitives_preserves_face_materials(tmp_path):
    import copy
    source=textured(tmp_path/'source.glb');doc=GLBDocument(source)
    a=doc.primitives[0];b=copy.deepcopy(a);faces=doc.faces(a)
    a['indices']=doc.append(faces[:6].reshape(-1,1),'SCALAR',5125)
    b['indices']=doc.append(faces[6:].reshape(-1,1),'SCALAR',5125)
    b['material']=1;doc.tree['materials'].append(copy.deepcopy(doc.tree['materials'][0]))
    doc.tree['materials'][1]['pbrMetallicRoughness']['metallicFactor']=.3
    doc.tree['meshes'][0]['primitives']=[a,b];doc.save(source)
    mesh=load_mesh(source);preserve_glb(source,mesh,tmp_path/'copy.glb')
    result=GLBDocument(tmp_path/'copy.glb')
    assert result.material_signature()==GLBDocument(source).material_signature()
    assert [(p['material'],len(result.faces(p))) for p in result.primitives]==[(0,6),(1,6)]


def test_external_texture_is_rejected(tmp_path):
    source=textured(tmp_path/'source.glb');doc=GLBDocument(source)
    doc.tree['images'][0]={'uri':'../../private.png'};doc.save(source)
    with pytest.raises(ToolFailure):GLBDocument(source)


def test_untextured_pbr_material_is_not_replaced_during_clean(tmp_path):
    mesh=trimesh.creation.box()
    mesh.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(baseColorFactor=[40,80,120,255],metallicFactor=.9,roughnessFactor=.12))
    source=tmp_path/'constant.glb';source.write_bytes(mesh.export(file_type='glb'))
    store=MeshStore(tmp_path);raw=store.import_mesh(source.name,uuid4())
    clean=store.clean(raw.run_id,raw.mesh_version,count_repair_round=False)
    assert clean.tool.succeeded
    record=store.get(raw.run_id,clean.tool.data['mesh_version'])
    assert GLBDocument(source).material_signature()==GLBDocument(tmp_path/record.relative_path).material_signature()
