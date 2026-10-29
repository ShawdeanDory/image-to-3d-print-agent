"""独立边界环质心扇形补片试验；未经完整复检，不用于生产修复。"""
from collections import defaultdict
import numpy as np
import trimesh


def centroid_fan_candidate(mesh,*,max_loop_vertices=512):
    if not 3<=max_loop_vertices<=512:
        raise ValueError('边界顶点上限须为3～512')
    vertices=np.asarray(mesh.vertices);faces=np.asarray(mesh.faces)
    if (vertices.ndim!=2 or vertices.shape[1]!=3 or not np.isfinite(vertices).all()
        or faces.ndim!=2 or faces.shape[1]!=3 or not len(faces) or len(faces)>5000000
        or faces.min()<0 or faces.max()>=len(vertices)):
        raise ValueError('候选输入须为有限有效三角网格')
    edges=np.vstack([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]])
    _,inverse,counts=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
    if np.any(counts>2):raise ValueError('存在非流形边，拒绝猜测补片')
    boundary=edges[counts[inverse]==1]
    outgoing=defaultdict(list);incoming=defaultdict(list)
    for a,b in boundary:outgoing[int(a)].append(int(b));incoming[int(b)].append(int(a))
    if any(len(outgoing[v])!=1 or len(incoming[v])!=1 for v in set(outgoing)|set(incoming)):
        raise ValueError('边界存在分支或方向冲突，拒绝猜测闭环')
    remaining=set(outgoing);loops=[]
    while remaining:
        start=min(remaining);loop=[];current=start
        while current in remaining:
            remaining.remove(current);loop.append(current);current=outgoing[current][0]
        if current!=start or len(loop)<3 or len(loop)>max_loop_vertices:
            raise ValueError('边界未闭合或超出顶点上限')
        loops.append(loop)
    if len(loops)>64:raise ValueError('边界环过多，不继续尝试')
    points=vertices.tolist();added=[]
    for loop in loops:
        center=len(points);points.append(vertices[loop].mean(axis=0).tolist())
        for i,a in enumerate(loop):added.append([center,loop[(i+1)%len(loop)],a])
    result=trimesh.Trimesh(vertices=points,faces=np.vstack([faces,np.array(added,dtype=int).reshape(-1,3)]),process=False)
    return result,{'method':'boundary_centroid_fan_experiment_v1','filled_loops':len(loops),
        'loop_vertices':[len(loop) for loop in loops],'added_faces':len(added),
        'original_vertices_and_faces_preserved':True,'production_approved':False,
        'requires':['self_intersection','wall_thickness','normals','watertight','non_manifold','shape_review']}
