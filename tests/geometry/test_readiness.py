"""新增检查不能被公共成功门槛忽略。"""
import pytest
from image_to_3d_print.schemas import MeshInspection, REQUIRED_CHECKS


@pytest.mark.parametrize('status', ['warn', 'fail', 'not_run'])
def test_additional_component_check_blocks_success(status):
    boolean={'finite_coordinates','watertight','normals','build_volume','bed_contact'}
    checks=[dict(name=name,status='pass',value=True if name in boolean else 0,
                 tool_version='known_fixture',evidence_artifact_id='fixture_report') for name in REQUIRED_CHECKS]
    checks.append(dict(name='components',status=status,value=None if status=='not_run' else 2,
                       tool_version='known_fixture',evidence_artifact_id='fixture_report',details={'reason':'需复核组件'}))
    inspection=MeshInspection(mesh_version='fixture_mesh',unit='mm',dimensions_mm=[10,10,10],volume_mm3=1000,
        component_count=2,watertight=True,normals_consistent=True,boundary_edge_count=0,
        non_manifold_edge_count=0,non_manifold_vertex_count=0,checks=checks)
    assert not inspection.ready_for_print
