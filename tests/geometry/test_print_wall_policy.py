"""0.5mm策略的确定性规则；这些测试不代表原生重网格已经验证。"""
from pathlib import Path
import numpy as np
import pytest
import trimesh
from image_to_3d_print.geometry.print_components import main_component,finish_components
from image_to_3d_print.print_config import PrintRepairConfig,wall_probe_tolerance
from image_to_3d_print.schemas import PrinterProfile


def parts():
    body=trimesh.creation.box(extents=[20,20,120])
    leaf=trimesh.creation.box(extents=[5,5,.4]);leaf.apply_translation([30,0,0])
    return body,leaf


def test_last_round_removes_only_separate_parts_and_archives(tmp_path):
    body,leaf=parts();source=trimesh.util.concatenate([leaf,body]);before=source.vertices.copy()
    result,facts=finish_components(source,tmp_path,phase=2)
    assert facts['input_components']==2 and facts['output_components']==1
    assert facts['removed_components'][0]['faces']==12
    assert facts['removed_components'][0]['dimensions_mm']==pytest.approx([5,5,.4])
    assert (tmp_path/'before-component-removal.stl').is_file()
    assert result.volume==pytest.approx(body.volume)
    np.testing.assert_array_equal(source.vertices,before)


def test_first_round_preserves_every_external_part(tmp_path):
    body,leaf=parts();source=trimesh.util.concatenate([body,leaf])
    result,facts=finish_components(source,tmp_path,phase=1)
    assert len(result.split())==2 and not facts['removed_components']


def test_main_is_not_selected_by_face_count():
    body,leaf=parts();leaf=trimesh.remesh.subdivide(leaf.vertices,leaf.faces)
    leaf=trimesh.Trimesh(*leaf,process=False)
    main,facts=main_component(trimesh.util.concatenate([leaf,body]))
    assert facts['selection']=='largest_closed_volume'
    assert main.volume==pytest.approx(body.volume)


def test_no_valid_body_is_an_error(tmp_path):
    with pytest.raises(ValueError,match='有效'):
        finish_components(trimesh.Trimesh(),tmp_path,phase=2)


def test_stl_duplicate_vertices_are_not_independent_shells(tmp_path):
    body,leaf=parts();path=tmp_path/'input.stl';trimesh.util.concatenate([body,leaf]).export(path)
    loaded=trimesh.load(path,force='mesh',process=False)
    _,facts=finish_components(loaded,tmp_path,phase=2)
    assert facts['input_components']==2 and len(facts['removed_components'])==1


def test_open_mesh_falls_back_to_area_and_archive_cannot_be_overwritten(tmp_path):
    body,leaf=parts();body.update_faces(np.arange(len(body.faces))!=0)
    source=trimesh.util.concatenate([body,leaf]);_,facts=finish_components(source,tmp_path,phase=2)
    assert facts['selection']=='largest_surface_area'
    with pytest.raises(ValueError,match='覆盖'):finish_components(source,tmp_path,phase=2)


def test_policy_config_and_profile_preserve_legacy():
    legacy=PrintRepairConfig(native_python='unused',native_paths=['unused'])
    assert legacy.policy=='legacy'
    profile=PrinterProfile.model_validate_json(Path('config/printer-profile-wall05.json').read_text(encoding='utf-8'))
    assert profile.min_wall_mm==.5 and wall_probe_tolerance(profile)==0
    old=PrinterProfile.model_validate_json(Path('fixtures/p1/printer_profile.json').read_text(encoding='utf-8'))
    assert old.min_wall_mm==1.2 and wall_probe_tolerance(old)==.02
    with pytest.raises(ValueError):PrintRepairConfig(native_python='unused',native_paths=['unused'],policy='anything')


@pytest.mark.parametrize('thickness',[.4,.5,.8])
def test_new_profile_probes_exact_minimum(thickness):
    # 这里只验证传给射线工具的门槛；实际厚度检出另由LinuxBlender测试负责。
    profile=PrinterProfile.model_validate_json(Path('config/printer-profile-wall05.json').read_text(encoding='utf-8'))
    tolerance=wall_probe_tolerance(profile)
    assert (thickness<profile.min_wall_mm-tolerance)==(thickness<.5)
