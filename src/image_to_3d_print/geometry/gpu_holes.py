"""首次PBR导出前的有界GPU补片；不把封闭通孔误称为已修复。"""
from contextlib import contextmanager
from typing import Literal
import time
from pydantic import Field
from ..schemas.common import ContractModel


class GPUHolePolicy(ContractModel):
    version: Literal['gpu-boundary-fill-v1'] = 'gpu-boundary-fill-v1'
    max_rounds: Literal[2] = 2
    perimeter_ratios: tuple[Literal[.12], Literal[.30]] = (.12, .30)
    max_diameter_ratio: float = Field(default=.10, gt=0, le=.10)
    max_patch_area_ratio: float = Field(default=.003, gt=0, le=.003)
    max_planarity_ratio: float = Field(default=.01, gt=0, le=.01)
    max_loop_edges: int = Field(default=512, ge=3, le=512)


def _edge_facts(vertices, faces):
    """边计数在CUDA上进行，原始面索引及方向不改。"""
    import torch
    edges=faces[:,[0,1,1,2,2,0]].reshape(-1,2).long()
    keys=edges.min(1).values*len(vertices)+edges.max(1).values
    order=torch.argsort(keys);sorted_keys=keys[order]
    unique,counts=torch.unique_consecutive(sorted_keys,return_counts=True)
    starts=torch.cumsum(counts,0)-counts
    directed=edges[order[starts[counts==1]]]
    return directed,int((counts>2).sum().item()),int((faces[:,0]==faces[:,1]).sum().item())


def repair_gpu_mesh(vertices, faces, policy=None):
    """GPU补片及复查；CPU仅处理少量边界连通关系，不执行模型推理。"""
    import torch
    import cumesh
    policy=policy or GPUHolePolicy()
    if not torch.cuda.is_available() or not vertices.is_cuda or not faces.is_cuda:
        raise RuntimeError('cuda_unavailable:GPU补洞不能静默回退CPU')
    start=time.perf_counter();vertices=vertices.contiguous();faces=faces.contiguous()
    if (vertices.ndim!=2 or vertices.shape[1]!=3 or faces.ndim!=2 or faces.shape[1]!=3
            or len(vertices)<3 or len(faces)<1 or not torch.isfinite(vertices).all()
            or faces.min()<0 or faces.max()>=len(vertices)):
        raise ValueError('invalid_mesh:GPU补洞输入无效')
    source_vertices=vertices;source_faces=faces
    extent=(vertices.max(0).values-vertices.min(0).values);scale=float(extent.max().item())
    if scale<=0:raise ValueError('invalid_mesh:零外形网格')
    before,nm_before,_=_edge_facts(vertices,faces)
    rounds=[];rejected={};total_patches=0
    for limit in policy.perimeter_ratios:
        directed,nm,_=_edge_facts(vertices,faces)
        if not len(directed):break
        edge_np=directed.cpu().numpy();neighbors={};directions={}
        for a,b in edge_np.tolist():
            neighbors.setdefault(a,[]).append(b);neighbors.setdefault(b,[]).append(a)
            directions[(min(a,b),max(a,b))]=(a,b)
        visited=set();caps=[];centers=[];patch_bounds=[];eligible=0;refused={}
        for seed in neighbors:
            if seed in visited:continue
            stack=[seed];component=[]
            while stack:
                v=stack.pop()
                if v in visited:continue
                visited.add(v);component.append(v);stack.extend(neighbors[v])
            reason=None
            if len(component)<3:reason='degenerate_boundary'
            elif len(component)>policy.max_loop_edges:reason='too_many_boundary_edges'
            elif any(len(neighbors[v])!=2 for v in component):reason='branched_boundary'
            if reason:
                refused[reason]=refused.get(reason,0)+1;continue
            ordered=[seed];previous=None;current=seed
            for _ in range(len(component)):
                next_v=next(v for v in neighbors[current] if v!=previous)
                if next_v==seed:break
                ordered.append(next_v);previous,current=current,next_v
            if len(ordered)!=len(component):
                refused['not_simple_loop']=refused.get('not_simple_loop',0)+1;continue
            ids=torch.tensor(ordered,device=vertices.device,dtype=torch.long)
            points=vertices[ids];center=points.mean(0);centered=points-center
            _,_,axes=torch.linalg.svd(centered,full_matrices=False)
            normal=axes[-1];plane=float((centered@normal).abs().max().item())
            diameter=float((points.max(0).values-points.min(0).values).norm().item())
            perimeter=float((points-points.roll(1,0)).norm(dim=1).sum().item())
            # 将每条边反向接到中心；若有内凹/混合方向，扇形补片不安全。
            directed_loop=[directions[(min(a,b),max(a,b))] for a,b in zip(ordered,ordered[1:]+ordered[:1])]
            edge_ids=torch.tensor(directed_loop,device=vertices.device,dtype=torch.long)
            cross=torch.cross(vertices[edge_ids[:,1]]-center,vertices[edge_ids[:,0]]-center,dim=1)
            area=float(cross.norm(dim=1).sum().item()/2)
            orientation=cross@normal
            if perimeter>limit*scale:reason='perimeter_limit'
            elif diameter>policy.max_diameter_ratio*scale:reason='diameter_limit'
            elif plane>max(1e-8,diameter*policy.max_planarity_ratio):reason='nonplanar_loop'
            elif area>policy.max_patch_area_ratio*scale*scale:reason='area_limit'
            elif not bool(((orientation>1e-12).all() or (orientation< -1e-12).all()).item()):reason='non_star_or_inconsistent_winding'
            if reason:
                refused[reason]=refused.get(reason,0)+1;continue
            low=points.min(0).values;high=points.max(0).values
            if any(bool(((low<=other_high)&(high>=other_low)).all().item()) for other_low,other_high in patch_bounds):
                refused['overlapping_patch_bounds']=refused.get('overlapping_patch_bounds',0)+1;continue
            # 在GPU BVH上逐条检查中心辐条是否穿过已有表面，拒绝遮盖现有面。
            bvh=cumesh.cuBVH(vertices,faces) if not caps else bvh
            rays=vertices[edge_ids[:,0]]-center;lengths=rays.norm(dim=1);dirs=rays/lengths[:,None]
            epsilon=max(scale*1e-6,1e-8)
            origins=center[None]+dirs*epsilon
            _,hit,depth=bvh.ray_trace(origins,dirs)
            obstructed=(hit>=0)&(depth>epsilon)&(depth<lengths-4*epsilon)
            distance,_,_=bvh.unsigned_distance((vertices[edge_ids[:,0]]+vertices[edge_ids[:,1]]+center)/3)
            if bool(obstructed.any().item()) or bool((distance<epsilon).any().item()):
                refused['existing_surface_intersection']=refused.get('existing_surface_intersection',0)+1;continue
            cid=len(vertices)+len(centers);centers.append(center)
            patch_bounds.append((low,high))
            caps.append(torch.cat([edge_ids.flip(1),torch.full((len(edge_ids),1),cid,device=faces.device,dtype=torch.long)],1))
            eligible+=1
        rejected=refused
        if not caps:continue
        candidate_v=torch.cat([vertices,torch.stack(centers)],0)
        candidate_f=torch.cat([faces,torch.cat(caps).to(faces.dtype)],0)
        after,nm_after,_=_edge_facts(candidate_v,candidate_f)
        accepted=len(after)<len(directed) and nm_after<=nm and torch.equal(candidate_v[:len(vertices)],vertices) and torch.equal(candidate_f[:len(faces)],faces)
        rounds.append({'round':len(rounds)+1,'perimeter_ratio':limit,'loops':eligible,
            'added_faces':len(candidate_f)-len(faces),'before_boundary_edges':len(directed),
            'after_boundary_edges':len(after),'nonmanifold_edges':nm_after,'accepted':bool(accepted)})
        if accepted:vertices,faces=candidate_v,candidate_f;total_patches+=eligible
    after,nm_after,_=_edge_facts(vertices,faces);torch.cuda.synchronize()
    report={'policy_version':policy.version,'device':torch.cuda.get_device_name(vertices.device),
        'status':'applied' if total_patches else 'unchanged','rounds':rounds,'attempts':len(rounds),
        'added_patches':total_patches,'added_faces':len(faces)-len(source_faces),
        'boundary_before':len(before),'boundary_after':len(after),'nonmanifold_before':nm_before,'nonmanifold_after':nm_after,
        'original_vertices_preserved':bool(torch.equal(vertices[:len(source_vertices)],source_vertices)),
        'original_faces_preserved':bool(torch.equal(faces[:len(source_faces)],source_faces)),
        'rejected_components':rejected,'seconds':time.perf_counter()-start,
        'closed_tunnels':'unsupported_not_repaired','semantic_hole_detection':'not_run',
        'full_self_intersection_check':'not_run','print_certified':False,
        'warning':'仅修补受控开放边界；带内壁的错误通孔、语义缺失和不安全边界仍可能保留，不能称为全部大洞修好。'}
    return vertices,faces,report


@contextmanager
def before_pbr_export(reports, snapshots=None):
    """独立模型子进程内，在首次UV/PBR采样前修补，不修改上游源码。"""
    import cumesh
    original=cumesh.CuMesh.uv_unwrap
    def wrapped(mesh,*args,**kwargs):
        vertices,faces=mesh.read()
        if snapshots is not None:snapshots.append((vertices.detach().clone(),faces.detach().clone()))
        try:vertices,faces,result=repair_gpu_mesh(vertices,faces)
        except (RuntimeError,ValueError,AssertionError) as exc:
            result=failed_gpu_report(exc)
        reports.append(result)
        if result['status']=='applied':mesh.init(vertices,faces)
        return original(mesh,*args,**kwargs)
    cumesh.CuMesh.uv_unwrap=wrapped
    try:yield
    finally:cumesh.CuMesh.uv_unwrap=original


def failed_gpu_report(exc):
    return {'policy_version':'gpu-boundary-fill-v1','status':'failed','attempts':1,'rounds':[],
        'added_patches':0,'added_faces':0,'boundary_before':None,'boundary_after':None,
        'error':{'code':'TOOL_UNAVAILABLE','message':type(exc).__name__+':'+str(exc)[:300]},
        'closed_tunnels':'unsupported_not_repaired','semantic_hole_detection':'not_run',
        'full_self_intersection_check':'not_run','print_certified':False,
        'warning':'GPU补片失败，未宣称修复；保留原几何继续首次材质导出，详情见工具记录。'}
