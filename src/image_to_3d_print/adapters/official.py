"""官方导出的只读坐标适配；不修改生成模型、纹理或网格拓扑。"""
from pathlib import Path
from typing import Literal
import numpy as np
import trimesh
from ..geometry.appearance import vertex_colors


def read_official_geometry(path: Path, frame: Literal['z_up','y_up']):
    if frame not in {'z_up','y_up'}:raise ValueError('未知官方坐标系')
    mesh=trimesh.load(path,force='mesh',process=False)
    vertices=np.asarray(mesh.vertices);faces=np.asarray(mesh.faces)
    if (not len(vertices) or not len(faces) or not np.isfinite(vertices).all()
            or faces.min()<0 or faces.max()>=len(vertices)):
        raise ValueError('官方导出不是有效网格')
    if frame=='y_up':
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,[1,0,0]))
    colors=vertex_colors(mesh)
    if colors is not None:mesh.visual=trimesh.visual.ColorVisuals(mesh,vertex_colors=colors)
    return mesh
