"""从最终毫米网格生成床面起柱的FDM支撑副本。"""
import math
from pathlib import Path

import numpy as np
import trimesh

from ..tools import ToolFailure, ToolSession
from .core import MeshStore, load_mesh


def _clip_height(triangle, x, y, half_width):
    """将三角形裁到柱体的XY范围内，求其中最低表面。"""
    polygon = list(triangle)
    for axis, center in enumerate((x, y)):
        for direction in (-1, 1):
            clipped = []
            if not polygon:
                return math.inf
            previous = polygon[-1]
            before = half_width - direction * (previous[axis] - center)
            for point in polygon:
                after = half_width - direction * (point[axis] - center)
                if (before >= 0) != (after >= 0):
                    clipped.append(previous + (point - previous) * (before / (before - after)))
                if after >= 0:
                    clipped.append(point)
                previous, before = point, after
            polygon = clipped
    return min((point[2] for point in polygon), default=math.inf)


def build_support_columns(mesh, nozzle, layer_height):
    """仅在从床面可达且留足顶部间隙的位置放置独立闭合柱。"""
    pitch, width = 12 * nozzle, 10 * nozzle
    half_width = width / 2
    lower, upper = mesh.bounds
    cells = np.floor((upper[:2] - lower[:2]) / pitch).astype(int) + 1
    if not mesh.is_volume or abs(lower[2]) > .01 or math.prod(cells) > 4096:
        raise ToolFailure('INVALID_ARGUMENT', '支撑需要闭合、已贴床且在支撑采样预算内的模型')

    triangles = mesh.triangles
    minimum, maximum = triangles.min(axis=1), triangles.max(axis=1)
    start = triangles[:, 0]
    edge_a, edge_b = triangles[:, 1] - start, triangles[:, 2] - start
    det = edge_a[:, 0] * edge_b[:, 1] - edge_a[:, 1] * edge_b[:, 0]
    normals_z = mesh.face_normals[:, 2]
    # 使用固定格距和居中的格点，避免支撑位置随世界原点变化。
    xs, ys = ((a + b) / 2 + (np.arange(n) - (n - 1) / 2) * pitch
              for a, b, n in zip(lower, upper, cells))
    columns = []
    blocked = 0
    for y in ys:
        row = np.flatnonzero((minimum[:, 1] <= y + half_width) & (maximum[:, 1] >= y - half_width))
        for x in xs:
            nearby = row[(minimum[row, 0] <= x + half_width) & (maximum[row, 0] >= x - half_width)]
            hits = nearby[np.abs(det[nearby]) > 1e-12]
            dx, dy = x - start[hits, 0], y - start[hits, 1]
            u = (dx * edge_b[hits, 1] - dy * edge_b[hits, 0]) / det[hits]
            v = (edge_a[hits, 0] * dy - edge_a[hits, 1] * dx) / det[hits]
            inside = (u >= -1e-8) & (v >= -1e-8) & (u + v <= 1 + 1e-8)
            hits = hits[inside]
            if not len(hits):
                continue
            heights = start[hits, 2] + u[inside] * edge_a[hits, 2] + v[inside] * edge_b[hits, 2]
            nearest = heights.argmin()
            center_z = heights[nearest]
            if center_z <= .01 or normals_z[hits[nearest]] >= -math.sqrt(.5):
                continue

            surface = center_z
            for index in nearby[minimum[nearby, 2] < center_z]:
                if minimum[index, 2] < surface:
                    surface = min(surface, _clip_height(triangles[index], x, y, half_width))
            top = math.floor((surface - layer_height + 1e-8) / layer_height) * layer_height
            # 斜面有间隙变化。若柱顶过低或附近已经被实体遮挡，跳过该点。
            if top < 2 * layer_height or center_z - top > 2 * layer_height + math.sqrt(2) * half_width:
                blocked += 1
                continue
            column = trimesh.creation.box(extents=(width, width, top))
            column.apply_translation((x, y, top / 2))
            columns.append(column)
    return columns, blocked


def export_supported_stl(root, run, version, inspection, profile, body_artifact_id):
    source = MeshStore(root).get(run, version)
    if (source.unit != 'mm' or inspection.mesh_version != version or not inspection.ready_for_print
            or source.parameters.get('printer_profile_id', profile.profile_id) != profile.profile_id):
        raise ToolFailure('STATE_CONFLICT', '自动支撑只接受同任务、同配置且几何复检通过的最终毫米网格')
    session = ToolSession(root, run, 'export', version)
    overhang = next(check for check in inspection.checks if check.name == 'overhang')
    if overhang.status == 'pass':
        return session.finish({'status': 'not_required', 'artifact_id': body_artifact_id, 'pillar_count': 0})

    mesh = load_mesh(Path(root) / source.relative_path)
    columns, blocked = build_support_columns(mesh, profile.nozzle_mm, profile.layer_height_mm)
    if not columns:
        return session.fail('INVALID_ARGUMENT', '检测到悬垂，但没有找到可从床面安全放置的支撑柱',
                            {'blocked_samples': blocked})
    combined = trimesh.util.concatenate([mesh, *columns])
    if profile.build_volume_mm is not None and np.any(combined.extents > profile.build_volume_mm):
        return session.fail('INVALID_ARGUMENT', '加支撑后的整体尺寸超过当前配置的打印空间')
    path = session.directory / 'supported.stl'
    combined.export(path)
    reread = trimesh.load(path, force='mesh', process=False)
    # 二进制STL以原顺序写三角面，逐面核对本体及新增支撑坐标。
    if (len(reread.faces) != len(combined.faces) or not np.isfinite(reread.vertices).all()
            or not np.allclose(reread.triangles, combined.triangles, rtol=0, atol=.01)):
        return session.fail('INVALID_ARGUMENT', '支撑STL读回与本体或支撑几何不一致')
    artifact = session.add('supported_stl', path, 'candidate_stl', 'mm', parents=(body_artifact_id,))
    return session.finish({'status': 'generated', 'artifact_id': artifact.artifact_id,
                           'pillar_count': len(columns), 'blocked_samples': blocked,
                           'top_gap_mm': profile.layer_height_mm,
                           'artifact_frames': {artifact.artifact_id: 'z_up'}})
