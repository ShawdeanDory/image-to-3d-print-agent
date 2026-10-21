from collections import defaultdict
import json
from pathlib import Path
import shutil
import math
from uuid import UUID,uuid4
from typing import Literal
import numpy as np
import trimesh
from ..schemas.common import ContractModel,Id,RelativePath
from ..schemas.task import ModelTaskRequest
from ..schemas.validation import resolve_artifact_path
from ..tools import ToolFailure,ToolSession,digest,new_directory
from .appearance import vertex_colors

class MeshVersion(ContractModel):
    run_id: UUID
    mesh_version: Id
    relative_path: RelativePath
    sha256: str
    unit: Literal['mm','unitless']
    parent: Id|None=None
    operation: str
    parameters: dict={}
    repair_round: int=0

def load_mesh(path):
    try:
        mesh=trimesh.load(path,force='mesh',process=False)
        v=np.asarray(mesh.vertices);f=np.asarray(mesh.faces)
        if (v.ndim!=2 or v.shape[1]!=3 or not len(v) or not np.isfinite(v).all()
            or f.ndim!=2 or f.shape[1]!=3 or not len(f) or f.min()<0 or f.max()>=len(v)):
            raise ValueError('非有效三角网格')
        if len(f)>5000000:raise ValueError('网格超过本工具500万面上限，需明确人工处理方案')
        # 仅合并数值完全相同的顶点，消除STL每面重复顶点，不做近似焊接。
        unique,first,inverse=np.unique(v,axis=0,return_index=True,return_inverse=True)
        result=trimesh.Trimesh(vertices=unique,faces=inverse[f],process=False)
        colors=vertex_colors(mesh)
        if colors is not None:result.visual.vertex_colors=colors[first]
        return result
    except (OSError,ValueError,AttributeError,TypeError,IndexError) as exc:
        raise ToolFailure('INVALID_ARGUMENT','网格为空、损坏、坐标/索引无效或超出范围') from exc

def topology(mesh):
    if len(mesh.faces)>100000:return _large_topology(mesh)
    faces=np.asarray(mesh.faces);edges=np.sort(np.vstack([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1)
    unique,inverse,counts=np.unique(edges,axis=0,return_inverse=True,return_counts=True)
    edge_faces=defaultdict(list)
    for edge,face in zip(inverse,np.tile(np.arange(len(faces)),3)):edge_faces[int(edge)].append(int(face))
    vertex_faces=defaultdict(set); adjacency=defaultdict(list)
    for i,face in enumerate(faces):
        for v in face:vertex_faces[int(v)].add(i)
    for edge,linked in edge_faces.items():
        for v in unique[edge]:
            if len(linked)==2:adjacency[int(v)].append(tuple(linked))
    bad_vertices=[]
    for v,linked in vertex_faces.items():
        neighbors=defaultdict(list)
        for a,b in adjacency[v]:neighbors[a].append(b);neighbors[b].append(a)
        seen=set(); stack=[next(iter(linked))]
        while stack:
            item=stack.pop()
            if item not in seen:seen.add(item);stack.extend(neighbors[item])
        # 顶点面扇必须连通；多面边的端点同时属于非流形顶点。
        if seen!=linked:bad_vertices.append(v)
    bad_edge_vertices=set(unique[counts>2].reshape(-1).tolist())
    bad_vertices=sorted(set(bad_vertices)|bad_edge_vertices)
    parents=list(range(len(faces)))
    def find(value):
        while parents[value]!=value:
            parents[value]=parents[parents[value]];value=parents[value]
        return value
    for linked in edge_faces.values():
        for face in linked[1:]:parents[find(face)]=find(linked[0])
    component_count=len({find(i) for i in range(len(faces))})
    parts=mesh.split(only_watertight=False)
    watertight=bool(np.all(counts==2))
    normals=bool(mesh.is_winding_consistent and (not watertight or all(p.volume>0 for p in parts)))
    return {'vertex_count':len(mesh.vertices),'face_count':len(faces),'component_count':component_count,
        'watertight':watertight,'normals_consistent':normals,'boundary_edge_count':int(np.sum(counts==1)),
        'non_manifold_edge_count':int(np.sum(counts>2)),'non_manifold_vertex_count':len(bad_vertices),
        'non_manifold_vertices':bad_vertices,'dimensions':mesh.extents.tolist(),
        'volume':float(mesh.volume) if watertight and normals else None}

def _large_topology(mesh):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    faces=np.asarray(mesh.faces);count=len(faces)
    edges=np.sort(np.vstack([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1)
    unique,inverse,counts=np.unique(edges,axis=0,return_inverse=True,return_counts=True)
    indices=inverse.reshape(3,count).T
    outgoing=np.column_stack([2*indices[:,i]+(faces[:,i]==unique[indices[:,i],1]) for i in range(3)]).reshape(-1)
    incoming=np.column_stack([2*indices[:,(i+2)%3]+(faces[:,i]==unique[indices[:,(i+2)%3],1]) for i in range(3)]).reshape(-1)
    graph=coo_matrix((np.ones(len(outgoing),dtype=np.uint8),(outgoing,incoming)),shape=(2*len(unique),2*len(unique))).tocsr()
    _,labels=connected_components(graph,directed=False)
    fans=np.unique(np.column_stack([unique.reshape(-1),labels]),axis=0)
    fan_counts=np.bincount(fans[:,0],minlength=len(mesh.vertices))
    bad=np.flatnonzero(fan_counts>1)
    bad=np.union1d(bad,unique[counts>2].reshape(-1))
    del graph,labels,fans,outgoing,incoming
    # 面与边的二部图按共享边联通；仅共享顶点的两个实体仍为两个组件。
    face_ids=np.tile(np.arange(count),3);edge_nodes=inverse+count
    graph=coo_matrix((np.ones(len(face_ids),dtype=np.uint8),(face_ids,edge_nodes)),shape=(count+len(unique),count+len(unique))).tocsr()
    component_count,labels=connected_components(graph,directed=False)
    labels=labels[:count]
    watertight=bool(np.all(counts==2))
    contributions=np.einsum('ij,ij->i',mesh.vertices[faces[:,0]],np.cross(mesh.vertices[faces[:,1]],mesh.vertices[faces[:,2]]))/6
    volumes=np.bincount(labels,weights=contributions)
    normals=bool(mesh.is_winding_consistent and (not watertight or np.all(volumes>0)))
    return {'vertex_count':len(mesh.vertices),'face_count':count,'component_count':int(component_count),
        'watertight':watertight,'normals_consistent':normals,'boundary_edge_count':int(np.sum(counts==1)),
        'non_manifold_edge_count':int(np.sum(counts>2)),'non_manifold_vertex_count':len(bad),'non_manifold_vertices':bad.tolist(),
        'dimensions':mesh.extents.tolist(),'volume':float(volumes.sum()) if watertight and normals else None}

def orient_and_scale(mesh,request:ModelTaskRequest,*,automatic_orientation=False):
    pending=[p for p in request.pending_inputs if not (p=='orientation' and automatic_orientation)]
    if pending:
        raise ToolFailure('INVALID_ARGUMENT','先确认高度、单位、尺度来源和朝上方向：'+','.join(request.pending_inputs))
    axis=request.orientation.up_axis
    source=np.zeros(3);source['xyz'.index(axis[-1])]=-1 if axis.startswith('-') else 1
    # 固定最短刚性旋转；绕朝上轴的角度不随对象临时选择。
    rotation=trimesh.geometry.align_vectors(source,[0,0,1])
    result=mesh.copy();result.apply_transform(rotation)
    height=result.extents[2]
    if not np.isfinite(height) or height<=1e-12:raise ToolFailure('INVALID_ARGUMENT','确认姿态下网格高度无效')
    scale=request.height_mm/height
    if not math.isfinite(request.height_mm) or not math.isfinite(scale):raise ToolFailure('INVALID_ARGUMENT','毫米换算或缩放溢出')
    scaling=np.diag([scale,scale,scale,1.])
    result.apply_transform(scaling)
    translation=np.eye(4);translation[2,3]=-result.bounds[0,2]
    result.apply_transform(translation)
    if not np.isfinite(result.vertices).all():raise ToolFailure('INVALID_ARGUMENT','定标后的坐标无效')
    return result,(translation@scaling@rotation).tolist()

class MeshStore:
    def __init__(self,root):self.root=Path(root).resolve()

    def _write(self,run,mesh,unit,operation,parent=None,parameters=None,repair_round=0,original_path=None):
        run=UUID(str(run));version='m_'+uuid4().hex[:24]
        folder=new_directory(self.root,f'runs/{run}/versions/{version}')
        if original_path:
            target=folder/('original'+Path(original_path).suffix.lower());shutil.copyfile(original_path,target)
        else:
            target=folder/'mesh.ply';mesh.export(target)
            read=load_mesh(target)
            if not np.allclose(mesh.extents,read.extents,atol=1e-5,rtol=1e-6):
                raise ToolFailure('INVALID_ARGUMENT','新网格独立读回尺寸不一致')
        record=MeshVersion(run_id=run,mesh_version=version,relative_path=target.relative_to(self.root).as_posix(),
            sha256=digest(target),unit=unit,parent=parent,operation=operation,parameters=parameters or {},repair_round=repair_round)
        (folder/'version.json').write_text(record.model_dump_json(indent=2)+'\n',encoding='utf-8')
        return record

    def import_mesh(self,relative,run,unit='unitless',parameters=None):
        try:source=resolve_artifact_path(self.root,relative)
        except ValueError as exc:raise ToolFailure('REFERENCE_NOT_FOUND','原始网格不存在或越界') from exc
        mesh=load_mesh(source)
        return self._write(run,mesh,unit,'import_original',parameters=parameters,original_path=source)

    def get(self,run,version):
        try:
            # 固定ID格式防止把版本当作路径。
            if not version.startswith('m_') or len(version)!=26 or not version[2:].isalnum():raise ValueError('ID')
            file=resolve_artifact_path(self.root,f'runs/{UUID(str(run))}/versions/{version}/version.json')
            record=MeshVersion.model_validate_json(file.read_text(encoding='utf-8'))
            path=resolve_artifact_path(self.root,record.relative_path)
            if record.run_id!=UUID(str(run)) or record.mesh_version!=version or path.parent!=file.parent or digest(path)!=record.sha256:
                raise ValueError('版本或摘要不一致')
            return record
        except (OSError,ValueError) as exc:raise ToolFailure('STATE_CONFLICT','版本不存在、归属不符或原始文件被修改') from exc

    def clean(self,run,version,*,count_repair_round=True):
        session=ToolSession(self.root,run,'repair',version)
        try:
            source=self.get(run,version)
            if source.repair_round>=2:raise ToolFailure('REPAIR_LIMIT_REACHED','最多两轮修复')
            mesh=load_mesh(self.root/source.relative_path);before=topology(mesh)
            mesh.update_faces(mesh.unique_faces());mesh.update_faces(mesh.nondegenerate_faces(height=1e-12))
            mesh.remove_unreferenced_vertices()
            if not len(mesh.faces):raise ToolFailure('INVALID_ARGUMENT','清理后为空网格')
            trimesh.repair.fix_normals(mesh,multibody=True)
            result=self._write(run,mesh,source.unit,'basic_clean',version,
                {'duplicate_and_degenerate_faces_removed':before['face_count']-len(mesh.faces),'normals_repaired':True,
                 'scope':'repair' if count_repair_round else 'preprocessing'},source.repair_round+int(count_repair_round))
            session.mesh_version=result.mesh_version
            artifact=session.add('mesh',self.root/result.relative_path,'repaired_mesh',source.unit)
            return session.finish({'mesh_version':result.mesh_version,'parent':version,'before':before,'after':topology(mesh),
                'version_record':result.model_dump(mode='json'),'mesh_artifact_id':artifact.artifact_id})
        except ToolFailure as exc:return session.fail(exc.code,str(exc))

    def scale(self,run,version,request:ModelTaskRequest,*,automatic_orientation=False):
        session=ToolSession(self.root,run,'repair',version)
        try:
            source=self.get(run,version);mesh=load_mesh(self.root/source.relative_path)
            original=source
            while original.parent is not None:original=self.get(run,original.parent)
            asset_id=original.parameters.get('input_asset_id')
            if asset_id is not None and request.image_asset_id!=asset_id:raise ToolFailure('STATE_CONFLICT','定标约束不属于本次重建图片')
            output,matrix=orient_and_scale(mesh,request,automatic_orientation=automatic_orientation)
            result=self._write(run,output,'mm','orient_scale_place',version,
                {'matrix':matrix,'height_mm':request.height_mm,'scale_source':request.scale_source,
                 'scale_evidence_id':request.scale_evidence_id,'orientation':request.orientation.model_dump(),
                 'orientation_policy':'automatic_policy' if automatic_orientation else 'confirmed_input',
                 'printer_profile_id':request.printer_profile_id},source.repair_round)
            session.mesh_version=result.mesh_version
            session.add('mesh',self.root/result.relative_path,'repaired_mesh','mm')
            return session.finish({'mesh_version':result.mesh_version,'version_record':result.model_dump(mode='json'),
                'dimensions_mm':output.extents.tolist(),'minimum_z_mm':float(output.bounds[0,2]),'bed_review_required':True})
        except ToolFailure as exc:return session.fail(exc.code,str(exc))
