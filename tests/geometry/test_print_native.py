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
