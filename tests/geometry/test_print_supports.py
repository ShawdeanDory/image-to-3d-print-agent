import numpy as np
import pytest
import trimesh

from image_to_3d_print.geometry.supports import build_support_columns
from image_to_3d_print.tools import ToolFailure


def test_columns_start_on_bed_clear_the_stem_and_leave_top_gap():
    outline = np.array([[-3, 0], [3, 0], [3, 12], [12, 12], [12, 18], [-12, 18], [-12, 12], [-3, 12]])
    triangles = np.array([[0, 1, 2], [0, 2, 7], [6, 7, 5], [7, 2, 5], [2, 4, 5], [2, 3, 4]])
    mesh = trimesh.creation.extrude_triangulation(outline, triangles, 16)
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    columns, blocked = build_support_columns(mesh, .4, .2)
    assert columns and blocked > 0  # 中心射线畅通但柱体会碰到立柱的点须跳过。
    for column in columns:
        lower, upper = column.bounds
        assert column.is_volume and lower[2] == pytest.approx(0)
        assert upper[2] == pytest.approx(11.8)
        assert upper[0] < -3 or lower[0] > 3
    assert len(trimesh.util.concatenate(columns).split()) == len(columns)


def test_no_columns_for_grounded_box_and_no_support_for_floating_mesh():
    mesh = trimesh.creation.box(extents=(20, 20, 10))
    mesh.apply_translation((0, 0, 5))
    assert build_support_columns(mesh, .4, .2) == ([], 0)
    mesh.apply_translation((0, 0, 1))
    with pytest.raises(ToolFailure, match='已贴床'):
        build_support_columns(mesh, .4, .2)
