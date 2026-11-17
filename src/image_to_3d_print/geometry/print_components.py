"""打印副本末轮部件政策；不修改输入或原始文件。"""
import numpy as np
import trimesh


def _parts(mesh):
    # STL逐三角形重复顶点；只合并完全相同的坐标，不跨空间间隙连接叶片。
    vertices,inverse=np.unique(mesh.vertices,axis=0,return_inverse=True)
    indexed=trimesh.Trimesh(vertices,inverse[mesh.faces],process=False)
    return list(indexed.split(only_watertight=False,repair=False))


def main_component(mesh):
    parts=_parts(mesh)
    if not parts or not all(len(p.faces) and np.isfinite(p.vertices).all() and p.area>0 for p in parts):
        raise ValueError('没有有效主体，不能执行副壳体删除')
    reliable=all(p.is_watertight and p.is_winding_consistent and abs(p.volume)>1e-9 for p in parts)
    selection='largest_closed_volume' if reliable else 'largest_surface_area'
    index=max(range(len(parts)),key=lambda i:((abs(parts[i].volume) if reliable else parts[i].area),parts[i].area,-i))
    return parts[index],{'selection':selection,'main_component_index':index,'component_count':len(parts)}


def finish_components(mesh,folder,*,phase):
    if phase not in (1,2):raise ValueError('副壳体政策仅允许两轮')
    main,selection=main_component(mesh)
    parts=_parts(mesh)
    facts={**selection,'input_components':len(parts),'output_components':len(parts),'removed_components':[]}
    if phase==1 or len(parts)==1:return mesh.copy(),facts
    archive=folder/'before-component-removal.stl'
    if archive.exists():raise ValueError('删除前备份已存在，拒绝覆盖')
    mesh.export(archive)
    for i,part in enumerate(parts):
        if i==selection['main_component_index']:continue
        facts['removed_components'].append({'index':i,'faces':len(part.faces),
            'dimensions_mm':part.extents.tolist(),'bounds_mm':part.bounds.tolist(),
            'area_mm2':float(part.area),'volume_mm3':abs(float(part.volume)) if part.is_volume else None})
    facts.update(output_components=1,archive=archive.name,
        reason='末轮有界融合后仍与主体分离，按用户授权删除；原件及完整候选保留')
    return main.copy(),facts
