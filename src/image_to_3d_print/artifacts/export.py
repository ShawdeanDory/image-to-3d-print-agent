from pathlib import Path
import numpy as np
from ..geometry.core import MeshStore,load_mesh
from .pbr import write_processed_glb
from ..tools import ToolFailure,ToolSession,digest

def _read_mm(file):
    from ..geometry.glb_preserve import GLBDocument
    mesh=load_mesh(file)
    if 'i3d' not in GLBDocument(file).tree.get('extras',{}):
        mesh.vertices=(mesh.vertices*1000)@np.array([[1,0,0],[0,0,1],[0,-1,0]])
    return mesh

def _check_same_geometry(mesh,reread):
    from scipy.spatial import cKDTree
    tolerance=max(.01,float(mesh.extents.max())*1e-5)
    if (len(mesh.faces)!=len(reread.faces) or len(mesh.vertices)!=len(reread.vertices)
        or cKDTree(mesh.vertices).query(reread.vertices)[0].max()>tolerance
        or cKDTree(reread.vertices).query(mesh.vertices)[0].max()>tolerance):
        raise ToolFailure('INVALID_ARGUMENT','GLB纹理导出改变了已检查网格的几何，停止交付')

def export_original(root,run,version):
    """只读登记同任务原GLB，不重导出、不烘焙、不套用副本尺度。"""
    from uuid import UUID
    from .pbr import AppearanceSource,_pbr_document
    session=ToolSession(root,run,'export',version)
    try:
        root=Path(root).resolve();source=MeshStore(root).get(run,version)
        while source.parent is not None:source=MeshStore(root).get(run,source.parent)
        record=source.parameters.get('appearance_source')
        if not record:raise ToolFailure('REFERENCE_NOT_FOUND','缺少本任务原始GLB来源，不以处理文件替代')
        original=AppearanceSource.model_validate(record);file=(root/original.relative_path).resolve()
        if not file.is_relative_to(root/f'runs/{UUID(str(run))}/tools'):
            raise ToolFailure('STATE_CONFLICT','原始GLB来源不属于本任务')
        if not file.is_file():raise ToolFailure('REFERENCE_NOT_FOUND','原始GLB文件不存在')
        if digest(file)!=original.sha256:raise ToolFailure('STATE_CONFLICT','原始GLB摘要已改变')
        document=_pbr_document(file);mesh=load_mesh(file)
        textured=any('baseColorTexture' in m.get('pbrMetallicRoughness',{}) for m in document.get('materials',[]))
        session.mesh_version=source.mesh_version
        artifact=session.add('original_glb',file,'raw_mesh','unitless')
        return session.finish({'artifact_id':artifact.artifact_id,'mesh_version':source.mesh_version,
            'inspection_mesh_version':version,'independent_readback':True,'original_unchanged':True,
            'target_scale_applied':False,'source_sha256':original.sha256,'face_count':len(mesh.faces),
            'artifact_frames':{artifact.artifact_id:original.frame},
            'appearance':{'policy_version':'original-glb-v1','status':'original_pbr' if textured else 'original_vertex_color',
                'mesh_version':source.mesh_version,'original_unchanged':True,'pbr_available':textured,
                'texture_size':original.texture_size if textured else None,'approximation':False}})
    except ToolFailure as exc:return session.fail(exc.code,str(exc))
    except (OSError,ValueError,KeyError) as exc:return session.fail('INVALID_ARGUMENT','原始GLB读取失败：'+str(exc)[:160])


def export_mesh(root,run,version,config=None):
    session=ToolSession(root,run,'export',version)
    try:
        source=MeshStore(root).get(run,version)
        if source.unit!='mm':raise ToolFailure('INVALID_ARGUMENT','导出候选STL前必须确认姿态和毫米尺度')
        mesh=load_mesh(Path(root)/source.relative_path)
        stl=session.directory/'candidate.stl';mesh.export(stl)
        # glTF规范为米、Y朝上；STL文件本身无单位，按毫米数值写入。
        rotation=np.array([[1,0,0],[0,0,1],[0,-1,0]])
        glb=session.directory/'model.glb'
        appearance=write_processed_glb(root,run,version,mesh,glb,session,config)
        stl_read=load_mesh(stl);glb_read=_read_mm(glb)
        _check_same_geometry(mesh,glb_read)
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
            'task_success':False,'appearance':appearance})
    except ToolFailure as exc:return session.fail(exc.code,str(exc))
    except (OSError,ValueError) as exc:return session.fail('INVALID_ARGUMENT','导出失败：'+str(exc)[:200])


def export_preview(root,run,version,config=None):
    """有效几何始终可以交付GLB；不生成或认证可打印STL。"""
    session=ToolSession(root,run,'export',version)
    try:
        source=MeshStore(root).get(run,version);mesh=load_mesh(Path(root)/source.relative_path)
        if source.unit!='mm':raise ToolFailure('INVALID_ARGUMENT','GLB交付需要明确的毫米尺度')
        rotation=np.array([[1,0,0],[0,0,1],[0,-1,0]])
        glb=session.directory/'model.glb'
        appearance=write_processed_glb(root,run,version,mesh,glb,session,config)
        reread=_read_mm(glb)
        if not np.allclose(mesh.extents,reread.extents,atol=max(.01,float(mesh.extents.max())*1e-5),rtol=0):
            raise ToolFailure('INVALID_ARGUMENT','GLB独立重读尺寸不一致')
        _check_same_geometry(mesh,reread)
        artifact=session.add('glb',glb,'repaired_mesh')
        return session.finish({'mesh_version':version,'artifact_id':artifact.artifact_id,'independent_readback':True,
            'dimensions_mm':mesh.extents.tolist(),'artifact_frames':{artifact.artifact_id:'y_up'},
            'source_sha256':source.sha256,'print_certified':False,'appearance':appearance})
    except ToolFailure as exc:return session.fail(exc.code,str(exc))
    except (OSError,ValueError) as exc:return session.fail('INVALID_ARGUMENT','GLB导出或读回失败')
