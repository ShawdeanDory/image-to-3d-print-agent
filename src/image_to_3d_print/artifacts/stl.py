"""只读序列化已交付的毫米几何；不修复模型、不更新任务或打印结论。"""
import hashlib
import io
from pathlib import Path

import numpy as np
import trimesh

from ..geometry.core import MeshStore, load_mesh
from ..runtime_contracts import GenerationTaskResponse
from ..schemas.validation import resolve_artifact_path
from ..tools import ToolFailure
from .export import _read_mm, _check_same_geometry


def delivery_stl(root, run_id, response, mesh_version):
    if response.get('schema_version') != 'generation-v1' or response.get('status') != 'succeeded':
        raise ToolFailure('STATE_CONFLICT', '仅已完成的毫米处理版可下载STL；历史原始无单位GLB不能隐式定标')
    task = GenerationTaskResponse.model_validate(response)
    delivery = task.delivery
    if str(task.run_id) != str(run_id) or delivery is None or delivery.mesh_version != mesh_version:
        raise ToolFailure('STATE_CONFLICT', '请求的STL与当前任务交付版本不一致，请刷新后重试')
    artifact = next((a for a in task.artifacts if a.artifact_id == delivery.artifact_id), None)
    if (artifact is None or str(artifact.run_id) != str(run_id) or artifact.mesh_version != mesh_version
            or artifact.kind != 'repaired_mesh' or artifact.unit != 'mm'):
        raise ToolFailure('STATE_CONFLICT', '交付GLB缺少同任务、同版本的毫米几何依据')
    try:
        glb = resolve_artifact_path(root, artifact.relative_path)
    except ValueError as exc:
        raise ToolFailure('REFERENCE_NOT_FOUND', '交付GLB不存在或文件路径越界') from exc
    source = MeshStore(root).get(run_id, mesh_version)
    if source.unit != 'mm':
        raise ToolFailure('STATE_CONFLICT', '网格尚未完成毫米定标，不能导出打印STL')
    mesh = load_mesh(Path(root) / source.relative_path)
    _check_same_geometry(mesh, _read_mm(glb))
    payload = mesh.export(file_type='stl')
    reread = trimesh.load(io.BytesIO(payload), file_type='stl', force='mesh', process=False)
    tolerance = max(.01, float(mesh.extents.max()) * 1e-5)
    if (len(reread.faces) != len(mesh.faces) or not np.isfinite(reread.vertices).all()
            or not np.allclose(mesh.extents, reread.extents, atol=tolerance, rtol=0)):
        raise ToolFailure('INVALID_ARGUMENT', 'STL独立读回的面数或毫米尺寸不一致，停止下载')
    return payload, {
        'Content-Disposition': f'attachment; filename="candidate-{run_id}.stl"',
        'Cache-Control': 'private, no-store',
        'X-Mesh-Version': mesh_version,
        'X-Mesh-Unit': 'mm',
        'X-Print-Check': delivery.print_check,
        'X-Print-Certified': 'false',
        'X-Content-SHA256': hashlib.sha256(payload).hexdigest(),
    }
