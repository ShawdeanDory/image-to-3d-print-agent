"""固定外观fixture；不使用模型/GPU或预存业务答案。"""
from pathlib import Path
import numpy as np
import pytest
import trimesh
from PIL import Image
from pydantic import ValidationError
from image_to_3d_print.adapters.reconstruction import BackendConfig
from image_to_3d_print.geometry.core import load_mesh


def textured_triangle():
    return trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[0,1,0]],faces=[[0,1,2]],process=False,
        visual=trimesh.visual.TextureVisuals(uv=[[0,0],[1,0],[0,1]],
            image=Image.fromarray(np.array([[[255,0,0],[0,255,0]],[[0,0,255],[255,255,0]]],dtype=np.uint8))))


def test_texture_readback_has_real_vertex_colors_without_geometry_change(tmp_path):
    source=textured_triangle();file=tmp_path/'source.glb';source.export(file)
    before=trimesh.load(file,force='mesh',process=False)
    result=load_mesh(file)
    assert result.visual.kind=='vertex'
    assert np.unique(result.visual.vertex_colors[:,:3],axis=0).shape[0]>=3
    assert np.allclose(result.extents,before.extents)
    assert len(result.faces)==len(before.faces)


def test_transfer_colors_keeps_target_geometry_and_no_color_stays_unknown():
    from image_to_3d_print.geometry.appearance import transfer_vertex_colors
    source=textured_triangle();target=source.copy();target.visual=trimesh.visual.ColorVisuals()
    vertices=target.vertices.copy();faces=target.faces.copy()
    record=transfer_vertex_colors(source,target)
    assert record['method']=='nearest_source_vertex_base_color'
    assert record['approximation'] is True
    assert target.visual.kind=='vertex'
    assert np.array_equal(vertices,target.vertices) and np.array_equal(faces,target.faces)
    empty=trimesh.creation.box();blank=empty.copy()
    assert transfer_vertex_colors(empty,blank)['status']=='not_available'
    assert blank.visual.kind is None


def test_course_profile_is_explicit_and_cannot_switch_backend():
    config=BackendConfig(backend='trellis2_candidate',python=Path('python'),execution_root=Path('.'),inference_profile='course_fast')
    assert config.inference_profile=='course_fast'
    with pytest.raises(ValidationError):
        BackendConfig(backend='triposr',python=Path('python'),execution_root=Path('.'),inference_profile='course_fast')
    with pytest.raises(ValidationError):
        BackendConfig(backend='trellis2_candidate',python=Path('python'),execution_root=Path('.'),inference_profile='course_fast',seed=0)


def test_color_survives_ply_export_clean_and_scale(tmp_path):
    from uuid import uuid4
    from image_to_3d_print.geometry.core import MeshStore
    from image_to_3d_print.schemas.task import ModelTaskRequest
    source=trimesh.creation.box();source.visual.vertex_colors=np.tile([241,192,5,255],(len(source.vertices),1))
    source.export(tmp_path/'source.ply');store=MeshStore(tmp_path);run=uuid4()
    original=store.import_mesh('source.ply',run)
    cleaned=store.clean(run,original.mesh_version)
    assert cleaned.tool.succeeded
    request=ModelTaskRequest(image_asset_id='fixed_image',printer_profile_id='demo_v1',height_value=10.,height_unit='mm',
        scale_source='user_target',orientation={'up_axis':'z','confirmed':True})
    scaled=store.scale(run,cleaned.tool.data['mesh_version'],request)
    record=store.get(run,scaled.tool.data['mesh_version']);mesh=load_mesh(tmp_path/record.relative_path)
    assert mesh.visual.kind=='vertex' and np.array_equal(mesh.visual.vertex_colors[0],[241,192,5,255])
    assert np.allclose(mesh.extents,[10.,10.,10.])


def test_new_task_profile_keeps_old_request_compatible():
    import json
    from image_to_3d_print.runtime_contracts import CreateTask
    request=json.loads(Path('fixtures/p1/contracts/request_pending.json').read_text(encoding='utf-8'))
    assert CreateTask(request=request).reconstruction_profile is None
    assert CreateTask(request=request,backend='trellis2_candidate',reconstruction_profile='course_fast').reconstruction_profile=='course_fast'
    with pytest.raises(ValidationError):
        CreateTask(request=request,backend='triposr',reconstruction_profile='course_fast')
