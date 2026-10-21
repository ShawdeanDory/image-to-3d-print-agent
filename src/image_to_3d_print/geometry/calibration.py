"""开发集共享刚性视角核验；不逐对象选择最高分，不消费保留集。"""
import math
import numpy as np
from ..measurement import render_silhouette,normalize_mask,mask_iou
from ..tools import ToolFailure

def choose_mapping(scores):
    if len(scores)<2 or any(len(values)<3 for values in scores.values()):raise ToolFailure('INVALID_ARGUMENT','至少两个映射、两个拟合例与一个独立开发核验例')
    ranked=sorted(scores,key=lambda key:(-float(np.mean(scores[key][:-1])),key))
    selected=ranked[0];margin=float(np.mean(scores[selected][:-1])-np.mean(scores[ranked[1]][:-1]))
    valid=margin>=.005 and min(scores[selected])>=.70
    return {'selected':selected,'status':'development_calibrated' if valid else 'needs_view_review',
        'fitting_mean':float(np.mean(scores[selected][:-1])),'separation_margin':margin,
        'validation_iou':scores[selected][-1],'reason':None if valid else '公共视角不唯一或开发核验低于0.70，保持真实质量未知'}

def candidate_rotations():
    result={}
    for yaw in [-180,-90,0,90]:
        for pitch in [-30,0,30]:
            z=math.radians(yaw);x=math.radians(pitch)
            rz=np.array([[math.cos(z),-math.sin(z),0],[math.sin(z),math.cos(z),0],[0,0,1]])
            rx=np.array([[1,0,0],[0,math.cos(x),-math.sin(x)],[0,math.sin(x),math.cos(x)]])
            result[f'yaw{yaw}_pitch{pitch}']=(rx@rz).tolist()
    return result

def calibrate_development(meshes,masks):
    if len(meshes)!=3 or len(masks)!=3:raise ToolFailure('INVALID_ARGUMENT','本最小口径固定两个开发拟合例和一个开发核验例')
    scores={};rotations=candidate_rotations()
    for key,rotation in rotations.items():
        scores[key]=[]
        for mesh,mask in zip(meshes,masks):
            rendered,_=render_silhouette(mesh.vertices,mesh.faces,rotation)
            scores[key].append(mask_iou(normalize_mask(mask),normalize_mask(rendered)).value)
    selected=choose_mapping(scores)
    return {**selected,'rotation':rotations[selected['selected']],'all_candidates':scores,
        'protocol_version':'1.0.0','method':'12_predeclared_rigid_candidates_shared_across_backend; last_case_not_used_for_selection',
        'coordinate_scope':'render_view_only; physical_up_axis_remains_z; no_mesh_modification',
        'quality_iou':scores[selected['selected']] if selected['status']=='development_calibrated' else None}
