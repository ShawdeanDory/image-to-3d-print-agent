"""仅显式配置隔离CPU依赖时运行；未配置则跳过，不能当作原生算法已通过。"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import numpy as np
import pytest
import trimesh


@pytest.fixture
def native():
    file=os.environ.get('I3D_PRINT_NATIVE_CONFIG')
    if not file:pytest.skip('未配置本机原生打印修复环境')
    config=json.loads(Path(file).read_text())
    for path in reversed(config['native_paths']):sys.path.insert(0,path)
    worker=Path(__file__).resolve().parents[2]/'scripts/tools/print_repair_worker.py'
    spec=importlib.util.spec_from_file_location('print_native_fixture',worker);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_native_closed_cube_keeps_geometry(native,tmp_path):
    source=trimesh.creation.box(extents=[30,40,120]);before=source.vertices.copy()
    result,facts=native.close_shells(source,tmp_path)
    assert result.is_watertight and result.is_winding_consistent
    np.testing.assert_allclose(result.extents,source.extents)
    np.testing.assert_array_equal(source.vertices,before)
    assert facts['remove_smallest_components'] is False


def test_native_larger_hole_closes_without_dropping_the_body(native,tmp_path):
    source=trimesh.creation.icosphere(subdivisions=2,radius=10)
    source.update_faces(source.triangles_center[:,2]<8);source.remove_unreferenced_vertices()
    assert not source.is_watertight
    result,_=native.close_shells(source,tmp_path)
    assert result.is_watertight and result.volume>3000


def test_native_separate_major_objects_are_rejected(native,tmp_path):
    a=trimesh.creation.box(extents=[20,20,20]);b=a.copy();b.apply_translation([40,0,0])
    with pytest.raises(ValueError,match='多个外部独立部件'):
        native.close_shells(trimesh.util.concatenate([a,b]),tmp_path)


def test_native_v2_preserves_external_components_first_round(native,tmp_path):
    body=trimesh.creation.box(extents=[20,20,120]);parts=[body]
    for i in range(18):
        leaf=trimesh.creation.box(extents=[2,2,.4]);leaf.apply_translation([30+i*4,0,0]);parts.append(leaf)
    result,facts=native.close_shells(trimesh.util.concatenate(parts),tmp_path,'wall05-components-v2')
    assert facts['external_components_kept']==19 and len(result.split())==19
    assert facts['removed_external_components']==[]


def test_native_v2_fuses_near_shell_and_removes_far_shell(native,tmp_path):
    body=trimesh.creation.box(extents=[20,20,120])
    near=trimesh.creation.box(extents=[2,2,2]);near.apply_translation([11.2,0,0])
    far=near.copy();far.apply_translation([20,0,0])
    source=trimesh.util.concatenate([body,near,far])
    result,facts=native.compensate(source,tmp_path,False,False,.5,120.,'wall05-components-v2')
    assert facts['fusion_attempted'] and facts['components']['input_components']==2
    assert facts['components']['output_components']==1 and len(facts['components']['removed_components'])==1
    assert result.is_watertight and result.extents[2]==pytest.approx(120.,abs=.01)
    assert result.bounds[1,0]>11 and result.bounds[1,0]<20
    assert (tmp_path/'before-component-removal.stl').is_file()


def test_native_v2_wraps_thin_plate_and_keeps_original(native,tmp_path):
    source=trimesh.creation.box(extents=[20,.4,120]);before=source.vertices.copy()
    result,facts=native.compensate(source,tmp_path,True,False,.5,120.,'wall05-components-v2')
    assert result.is_watertight and result.extents[1]>.5
    assert facts['offset_mm']==pytest.approx(.35) and facts['voxel_mm']==.2
    np.testing.assert_array_equal(source.vertices,before)


@pytest.mark.parametrize('thickness,expected',[(.4,True),(.5,False),(.8,False)])
def test_linux_blender_half_mm_threshold(tmp_path,thickness,expected):
    file=os.environ.get('I3D_PRINT_INSPECTION_CONFIG')
    if not file:pytest.skip('未配置LinuxBlender原生厚度检查')
    from image_to_3d_print.inspection.service import InspectionConfig,blender_call
    config=InspectionConfig.model_validate_json(Path(file).read_text(encoding='utf-8'))
    source=trimesh.creation.box(extents=[20,thickness,120])
    facts=blender_call(config,'inspect',source,tmp_path,
        {'unit':'mm','min_wall_mm':.5,'wall_tolerance_mm':0.})
    assert bool(facts['thin_faces_low'])==expected
    assert facts['thin_faces_high']==facts['thin_faces_low']
