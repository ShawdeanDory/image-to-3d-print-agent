import numpy as np
import pytest
import trimesh
from image_to_3d_print.geometry.hole_experiment import centroid_fan_candidate
from image_to_3d_print.geometry.core import topology


def test_planar_hole_candidate_only_appends_and_closes():
    mesh=trimesh.creation.box(extents=[10,10,10])
    mesh.update_faces(mesh.face_normals[:,2]<.9)
    before_v=mesh.vertices.copy();before_f=mesh.faces.copy()
    candidate,report=centroid_fan_candidate(mesh)
    assert topology(candidate)['boundary_edge_count']==0
    assert candidate.is_winding_consistent
    assert report['filled_loops']==1 and report['added_faces']==4
    assert report['production_approved'] is False
    np.testing.assert_array_equal(candidate.vertices[:len(before_v)],before_v)
    np.testing.assert_array_equal(candidate.faces[:len(before_f)],before_f)
    np.testing.assert_array_equal(mesh.faces,before_f)


def test_closed_mesh_kept_and_oversized_loop_rejected():
    mesh=trimesh.creation.box()
    result,report=centroid_fan_candidate(mesh)
    assert len(result.faces)==len(mesh.faces) and report['filled_loops']==0
    mesh.update_faces(mesh.face_normals[:,2]<.9)
    with pytest.raises(ValueError,match='边界'):
        centroid_fan_candidate(mesh,max_loop_vertices=3)


def test_nonmanifold_boundary_does_not_silently_guess():
    mesh=trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[0,1,0],[-1,0,0],[0,-1,0]],
        faces=[[0,1,2],[0,3,4]],process=False)
    with pytest.raises(ValueError,match='分支'):
        centroid_fan_candidate(mesh)


def test_concave_loop_centroid_fan_can_close_but_has_inverted_patch():
    # U形管口的均值质心在凹槽外；无条件扇形补片不是可靠通用算法。
    polygon=np.array([[0,0],[3,0],[3,3],[2,3],[2,1],[1,1],[1,3],[0,3]],float)
    vertices=np.vstack([np.column_stack([polygon,np.zeros(8)]),np.column_stack([polygon,np.ones(8)])])
    faces=[]
    for a in range(8):
        b=(a+1)%8;faces.extend([[a,b,b+8],[a,b+8,a+8]])
    mesh=trimesh.Trimesh(vertices,faces,process=False)
    candidate,report=centroid_fan_candidate(mesh)
    assert candidate.is_watertight and report['production_approved'] is False
    top=candidate.face_normals[len(faces):len(faces)+8,2]
    assert np.any(top>0) and np.any(top<0)
