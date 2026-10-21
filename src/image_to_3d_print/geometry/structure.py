"""结构操作先生成提案；确认绑定本任务、本版本和具体预览。"""
import json
from pathlib import Path
from typing import Literal
from uuid import UUID,uuid4
import numpy as np
from pydantic import Field,StrictInt
from ..schemas.common import ContractModel,Id,RelativePath,Text
from ..tools import ToolFailure,ToolSession,digest,new_directory
from ..schemas.validation import resolve_artifact_path
from ..measurement import render_silhouette,normalize_mask,mask_iou
from ..inspection.service import blender_call
from .core import MeshStore,load_mesh,topology
from .appearance import transfer_vertex_colors

class StructureRequest(ContractModel):
    operation: Literal['fill_small_holes','remove_components','simplify']
    max_perimeter_mm: float=Field(default=40,gt=0,le=40,strict=True)
    remove_components: list[StrictInt]=Field(default_factory=list)
    target_faces: StrictInt=Field(default=100000,ge=100,le=500000)
    min_wall_mm: float=Field(default=1.2,gt=0)

class Proposal(ContractModel):
    proposal_id: Id
    run_id: UUID
    source_version: Id
    source_sha256: str
    request: StructureRequest
    preview_path: RelativePath
    preview_sha256: str
    preview_glb_path: RelativePath
    preview_glb_sha256: str
    changes: dict

def _proposal(root,run,proposal_id):
    if not proposal_id.startswith('p_') or len(proposal_id)!=26 or not proposal_id[2:].isalnum():raise ToolFailure('REFERENCE_NOT_FOUND','提案ID无效')
    folder=Path(root)/f'runs/{UUID(str(run))}/proposals/{proposal_id}'
    if not folder.resolve().is_relative_to(Path(root).resolve()):raise ToolFailure('REFERENCE_NOT_FOUND','提案越界')
    try:record=Proposal.model_validate_json((folder/'proposal.json').read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:raise ToolFailure('REFERENCE_NOT_FOUND','提案不存在或无效') from exc
    if record.run_id!=UUID(str(run)) or record.proposal_id!=proposal_id:raise ToolFailure('STATE_CONFLICT','提案不属于本任务')
    return folder,record

def _fill_small(mesh,limit):
    edges=np.sort(mesh.edges,axis=1);unique,counts=np.unique(edges,axis=0,return_counts=True)
    boundary=unique[counts==1];neighbors={}
    for a,b in boundary:
        neighbors.setdefault(int(a),[]).append(int(b));neighbors.setdefault(int(b),[]).append(int(a))
    seen=set();added=[];loops=[]
    for start in sorted(neighbors):
        if start in seen:continue
        if any(len(neighbors[v])!=2 for v in neighbors):raise ToolFailure('INVALID_ARGUMENT','边界不是简单闭环，不支持自动补洞')
        loop=[start];previous=None;current=start
        while True:
            following=next(v for v in neighbors[current] if v!=previous)
            if following==start:break
            if following in loop:raise ToolFailure('INVALID_ARGUMENT','边界拓扑不支持')
            loop.append(following);previous,current=current,following
        seen.update(loop)
        points=mesh.vertices[loop];perimeter=float(np.linalg.norm(points-np.roll(points,-1,axis=0),axis=1).sum())
        if len(loop) not in {3,4} or perimeter>limit+1e-6:
            raise ToolFailure('INVALID_ARGUMENT','仅支持确认的3/4边小型平面孔洞，其他开口须人工处理')
        normal=np.cross(points[1]-points[0],points[2]-points[0]);length=np.linalg.norm(normal)
        if length<1e-12 or abs(np.dot(points[-1]-points[0],normal/length))>1e-5:
            raise ToolFailure('INVALID_ARGUMENT','孔洞退化或非平面')
        if len(loop)==4 and any(np.dot(np.cross(points[(i+1)%4]-points[i],points[(i+2)%4]-points[(i+1)%4]),normal)<=0 for i in range(4)):
            raise ToolFailure('INVALID_ARGUMENT','仅支持凸平面小孔，不猜测复杂开口')
        # 根据相邻已有有向边确定新增面反向，保持边绕向一致。
        a,b=loop[:2]
        directed=any(any(int(face[i])==a and int(face[(i+1)%3])==b for i in range(3)) for face in mesh.faces)
        if directed:loop.reverse()
        added.extend([[loop[0],loop[i],loop[i+1]] for i in range(1,len(loop)-1)])
        loops.append({'vertex_indices':loop,'perimeter_mm':perimeter})
    if not added:raise ToolFailure('INVALID_ARGUMENT','没有可识别的小孔洞')
    output=mesh.copy();output.faces=np.vstack([mesh.faces,added])
    return output,{'filled_loops':loops,'added_faces':len(added)}

def preservation(before,after):
    rotations=[((1,0,0),(0,1,0),(0,0,1)),((1,0,0),(0,0,-1),(0,1,0)),((0,0,1),(0,1,0),(-1,0,0))]
    scores=[]
    for rotation in rotations:
        a,_=render_silhouette(before.vertices,before.faces,rotation);b,_=render_silhouette(after.vertices,after.faces,rotation)
        scores.append(mask_iou(normalize_mask(a),normalize_mask(b)).value)
    relative=float(np.max(np.abs(before.extents-after.extents)/np.maximum(before.extents,1e-9)))
    old,new=topology(before),topology(after)
    good=(min(scores)>=.95 and relative<=.01 and old['component_count']==new['component_count']
        and all(new[key]<=old[key] for key in ['boundary_edge_count','non_manifold_edge_count','non_manifold_vertex_count'])
        and (not old['watertight'] or new['watertight']) and (not old['normals_consistent'] or new['normals_consistent']))
    return {'fixed_three_view_iou':scores,'max_relative_dimension_change':relative,'preservation_pass':good,'before':old,'after':new}

def propose(root,run,version,request:StructureRequest,config=None):
    store=MeshStore(root);source=store.get(run,version)
    if source.repair_round>=2:raise ToolFailure('REPAIR_LIMIT_REACHED','已达到两轮修复上限')
    mesh=load_mesh(Path(root)/source.relative_path)
    session=ToolSession(root,run,'repair',version)
    if request.operation=='fill_small_holes':
        if source.unit!='mm':raise ToolFailure('INVALID_ARGUMENT','小孔周长需要已确认的毫米尺度')
        preview,changes=_fill_small(mesh,request.max_perimeter_mm)
    elif request.operation=='remove_components':
        facts=topology(mesh)
        if facts['non_manifold_edge_count'] or facts['non_manifold_vertex_count']:
            raise ToolFailure('INVALID_ARGUMENT','先处理非流形缺陷，再预览独立组件，不能把断开的面扇当作待删物体')
        parts=list(mesh.split(only_watertight=False));selected=request.remove_components
        if not selected or len(selected)!=len(set(selected)) or any(i<0 or i>=len(parts) for i in selected) or len(selected)>=len(parts):
            raise ToolFailure('INVALID_ARGUMENT','必须明确删除具体组件且至少保留一个，不能默认保留最大件')
        import trimesh
        preview=trimesh.util.concatenate([part for i,part in enumerate(parts) if i not in selected])
        changes={'removed_component_indices':selected,'components':[{'index':i,'faces':len(p.faces),'bounds':p.bounds.tolist()} for i,p in enumerate(parts)]}
    else:
        if source.unit!='mm':raise ToolFailure('INVALID_ARGUMENT','简化保形及薄壁复查需要先确认毫米尺度')
        if len(mesh.faces)<=100000 or request.target_faces>=len(mesh.faces):raise ToolFailure('INVALID_ARGUMENT','只有超过10万面且目标更小时才允许简化')
        result=blender_call(config,'simplify',mesh,session.directory,{'unit':source.unit,'target_faces':request.target_faces})
        import trimesh
        preview=trimesh.Trimesh(vertices=result['vertices'],faces=result['faces'],process=False)
        changes=preservation(mesh,preview)
        changes['appearance']=transfer_vertex_colors(mesh,preview)
        changes['appearance']['source_version']=version
        # 简化还须在同一工具/尺度下复查自交和壁厚，不只比较面数。
        for name,candidate in [('before',mesh),('after',preview)]:
            if name=='before' and len(candidate.faces)>500000:
                changes['before_checks']={'status':'not_run','reason':'原始超大网格逐面打印检查超时基线已保留；不把未知当作通过'}
                continue
            directory=new_directory(root,f'{session.relative}/{name}')
            checked=blender_call(config,'inspect',candidate,directory,{'unit':source.unit,'min_wall_mm':request.min_wall_mm})
            changes[name+'_checks']={key:len(checked[key]) for key in ['self_intersection_faces','thin_faces_low','thin_faces_high']}
        if changes['before_checks'].get('status')!='not_run' and any(changes['after_checks'][key]>0 and changes['before_checks'][key]==0 for key in changes['before_checks']):changes['preservation_pass']=False
        changes['printing_pass']=False
        changes['printing_gate']='需对批准后的具体新版本完整检查及独立预览/切片，提案不是合格交付'
        if not changes['preservation_pass']:raise ToolFailure('INVALID_ARGUMENT','简化未通过保形/拓扑/尺寸/打印缺陷回归，不接受此版本')
    if 'before' not in changes:changes['before']=topology(mesh)
    if 'after' not in changes:changes['after']=topology(preview)
    changes['requires_human_confirmation']=True
    proposal_id='p_'+uuid4().hex[:24];folder=new_directory(root,f'runs/{UUID(str(run))}/proposals/{proposal_id}')
    path=folder/'preview.ply';preview.export(path)
    glb=folder/'preview.glb';visual=preview.copy()
    visual.vertices=(visual.vertices@np.array([[1,0,0],[0,0,1],[0,-1,0]]).T)*(.001 if source.unit=='mm' else 1.)
    visual.export(glb)
    record=Proposal(proposal_id=proposal_id,run_id=run,source_version=version,source_sha256=source.sha256,request=request,
        preview_path=path.relative_to(Path(root).resolve()).as_posix(),preview_sha256=digest(path),
        preview_glb_path=glb.relative_to(Path(root).resolve()).as_posix(),preview_glb_sha256=digest(glb),changes=changes)
    (folder/'proposal.json').write_text(record.model_dump_json(indent=2)+'\n',encoding='utf-8')
    return record

def confirm(root,run,proposal_id,reviewer,accepted,origin='human'):
    if not reviewer or not isinstance(accepted,bool) or origin not in {'human','test_fixture'}:
        raise ToolFailure('INVALID_ARGUMENT','必须提供实际复核人、布尔决定及来源')
    folder,record=_proposal(root,run,proposal_id)
    confirmation={'run_id':str(run),'proposal_id':proposal_id,'source_version':record.source_version,'reviewer':reviewer,
        'accepted':accepted,'origin':origin,'proposal_sha256':digest(folder/'proposal.json'),'preview_sha256':record.preview_sha256,
        'preview_glb_sha256':record.preview_glb_sha256}
    file=folder/'confirmation.json'
    if file.exists():
        if json.loads(file.read_text(encoding='utf-8'))!=confirmation:raise ToolFailure('STATE_CONFLICT','该提案已作不同确认')
    else:file.write_text(json.dumps(confirmation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return confirmation

def apply_proposal(root,run,proposal_id):
    folder,record=_proposal(root,run,proposal_id);store=MeshStore(root)
    session=ToolSession(root,run,'repair',record.source_version)
    try:
        source=store.get(run,record.source_version)
        if source.sha256!=record.source_sha256 or source.repair_round>=2:raise ToolFailure('STATE_CONFLICT','源版本变化或修复已达上限')
        try:confirmation=json.loads((folder/'confirmation.json').read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc:raise ToolFailure('STATE_CONFLICT','尚未确认，不执行结构性修改') from exc
        preview=resolve_artifact_path(root,record.preview_path)
        preview_glb=resolve_artifact_path(root,record.preview_glb_path)
        if preview.parent!=folder.resolve():raise ToolFailure('STATE_CONFLICT','预览文件不属于本提案')
        if (not confirmation['accepted'] or confirmation['proposal_sha256']!=digest(folder/'proposal.json')
            or confirmation['preview_sha256']!=digest(preview) or confirmation['preview_glb_sha256']!=digest(preview_glb)
            or confirmation['source_version']!=source.mesh_version):
            raise ToolFailure('STATE_CONFLICT','确认拒绝或不匹配本提案/预览/源版本')
        marker=folder/'applied.json'
        if marker.exists():return session.finish({'already_applied':True,**json.loads(marker.read_text())})
        mesh=load_mesh(preview)
        result=store._write(run,mesh,source.unit,record.request.operation,source.mesh_version,
            {'proposal_id':proposal_id,'confirmation':confirmation,'changes':record.changes},source.repair_round+1)
        session.mesh_version=result.mesh_version
        session.add('mesh',Path(root)/result.relative_path,'repaired_mesh',source.unit)
        session.add('confirmation',folder/'confirmation.json','inspection_report')
        data={'mesh_version':result.mesh_version,'proposal_id':proposal_id,'confirmation_origin':confirmation['origin']}
        marker.write_text(json.dumps(data)+'\n',encoding='utf-8')
        return session.finish(data)
    except ToolFailure as exc:return session.fail(exc.code,str(exc))
