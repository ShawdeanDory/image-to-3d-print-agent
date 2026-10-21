"""只处理底色，不改变坐标、面或打印结论；原始PBR另行保留。"""
import numpy as np


def vertex_colors(mesh):
    if mesh.visual.kind=='texture':
        visual=mesh.visual.to_color()
    elif mesh.visual.kind in {'vertex','face'}:
        visual=mesh.visual
    else:return None
    colors=np.asarray(visual.vertex_colors,dtype=np.uint8)
    return colors if colors.shape==(len(mesh.vertices),4) else None


def transfer_vertex_colors(source,target):
    colors=vertex_colors(source)
    if colors is None:return {'status':'not_available','method':None,'approximation':False}
    from scipy.spatial import cKDTree
    distances,indices=cKDTree(np.asarray(source.vertices)).query(np.asarray(target.vertices))
    target.visual.vertex_colors=colors[indices]
    return {'status':'available','method':'nearest_source_vertex_base_color','approximation':True,
        'max_distance_source_units':float(distances.max()),'pbr_material_preserved':False}
