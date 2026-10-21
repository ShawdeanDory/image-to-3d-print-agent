from pathlib import Path
import numpy as np
from ..geometry.core import MeshStore,load_mesh
from ..tools import ToolFailure,ToolSession

def export_mesh(root,run,version):
    session=ToolSession(root,run,'export',version)
    try:
        source=MeshStore(root).get(run,version)
        if source.unit!='mm':raise ToolFailure('INVALID_ARGUMENT','导出候选STL前必须确认姿态和毫米尺度')
        mesh=load_mesh(Path(root)/source.relative_path)
        stl=session.directory/'candidate.stl';mesh.export(stl)
        # glTF规范为米、Y朝上；STL文件本身无单位，按毫米数值写入。
        rotation=np.array([[1,0,0],[0,0,1],[0,-1,0]])
        gltf=mesh.copy();gltf.vertices=(mesh.vertices@rotation.T)*.001
        glb=session.directory/'model.glb';gltf.export(glb)
        stl_read=load_mesh(stl);glb_read=load_mesh(glb)
        glb_read.vertices=(glb_read.vertices*1000)@rotation
        tolerance=max(.01,float(mesh.extents.max())*1e-5)
        for loaded in [stl_read,glb_read]:
            if not np.allclose(mesh.extents,loaded.extents,atol=tolerance,rtol=0):
                raise ToolFailure('INVALID_ARGUMENT','导出独立重读尺寸不一致，停止交付')
        session.add('stl',stl,'candidate_stl','mm')
        session.add('glb',glb,'repaired_mesh')
        return session.finish({'mesh_version':version,'source_sha256':source.sha256,
            'dimensions_mm':mesh.extents.tolist(),'stl_dimensions_mm':stl_read.extents.tolist(),
            'glb_reread_dimensions_mm':glb_read.extents.tolist(),'stl_convention':'unitless_file_coordinates_interpreted_as_mm',
            'glb_convention':'meters_y_up; inverse_transform_reread_as_mm_z_up',
            'logical_mesh_unit':'mm','independent_readback':True,'printability':'requires_inspection_preview_and_slicer_confirmation',
            'task_success':False})
    except ToolFailure as exc:return session.fail(exc.code,str(exc))
    except (OSError,ValueError) as exc:return session.fail('INVALID_ARGUMENT','导出失败：'+str(exc)[:200])


def export_preview(root,run,version):
    """有效几何始终可以交付GLB；不生成或认证可打印STL。"""
    session=ToolSession(root,run,'export',version)
    try:
        source=MeshStore(root).get(run,version);mesh=load_mesh(Path(root)/source.relative_path)
        if source.unit!='mm':raise ToolFailure('INVALID_ARGUMENT','GLB交付需要明确的毫米尺度')
        rotation=np.array([[1,0,0],[0,0,1],[0,-1,0]])
        visual=mesh.copy();visual.vertices=(visual.vertices@rotation.T)*.001
        glb=session.directory/'model.glb';visual.export(glb)
        reread=load_mesh(glb);reread.vertices=(reread.vertices*1000)@rotation
        if not np.allclose(mesh.extents,reread.extents,atol=max(.01,float(mesh.extents.max())*1e-5),rtol=0):
            raise ToolFailure('INVALID_ARGUMENT','GLB独立重读尺寸不一致')
        artifact=session.add('glb',glb,'repaired_mesh')
        return session.finish({'mesh_version':version,'artifact_id':artifact.artifact_id,'independent_readback':True,
            'dimensions_mm':mesh.extents.tolist(),'artifact_frames':{artifact.artifact_id:'y_up'},
            'source_sha256':source.sha256,'print_certified':False})
    except ToolFailure as exc:return session.fail(exc.code,str(exc))
    except (OSError,ValueError) as exc:return session.fail('INVALID_ARGUMENT','GLB导出或读回失败')
