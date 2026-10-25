"""只处理底色，不改变坐标、面或打印结论；原始PBR另行保留。"""
import numpy as np


def smooth_vertex_normals(mesh):
    """查看法线有限且单位长度；退化/孤立点不改变几何。"""
    normals=np.asarray(mesh.vertex_normals).copy()
    invalid=~np.isfinite(normals).all(axis=1)|(np.linalg.norm(normals,axis=1)<1e-10)
    if invalid.any():
        faces=np.asarray(mesh.faces);face_normals=np.asarray(mesh.face_normals)
        valid=np.isfinite(face_normals).all(axis=1)&(np.linalg.norm(face_normals,axis=1)>1e-10)
        replacements=np.zeros_like(normals);replacements[faces[valid].reshape(-1)]=np.repeat(face_normals[valid],3,axis=0)
        normals[invalid]=replacements[invalid]
        remaining=np.linalg.norm(normals,axis=1)<1e-10
        if remaining.any():
            from scipy.spatial import cKDTree
            good=~remaining
            if good.any():normals[remaining]=normals[good][cKDTree(np.asarray(mesh.vertices)[good]).query(np.asarray(mesh.vertices)[remaining])[1]]
            else:normals[:]=[0,0,1]
    normals/=np.linalg.norm(normals,axis=1)[:,None]
    return normals


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


def export_base_color_glb(mesh):
    """处理PLY的sRGB底色按glTF线性顶点色导出，原始纹理材质不覆盖。"""
    from trimesh.exchange.gltf import export_glb
    mesh=mesh.copy();mesh.vertex_normals=smooth_vertex_normals(mesh)
    if mesh.visual.kind not in {'vertex','face'}:
        return export_glb(mesh,include_normals=True)

    def colors_to_linear(buffers,tree):
        accessors=list(tree['accessors'].values());keys=list(buffers)
        for item in tree['meshes']:
            for primitive in item['primitives']:
                index=primitive['attributes'].get('COLOR_0')
                if index is None:continue
                accessor=accessors[index];key=keys[accessor['bufferView']]
                rgba=np.frombuffer(buffers[key],dtype=np.uint8).reshape(-1,4).astype(np.float32)/255
                rgb=rgba[:,:3]
                rgba[:,:3]=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
                buffers[key]=rgba.astype('<f4').tobytes()
                accessor.update(componentType=5126,min=rgba.min(axis=0).tolist(),max=rgba.max(axis=0).tolist())
                accessor.pop('normalized',None)

    def explicit_material(tree):
        materials=tree.setdefault('materials',[]);index=len(materials)
        materials.append({'name':'processed_base_color','doubleSided':True,
            'pbrMetallicRoughness':{'baseColorFactor':[1.,1.,1.,1.],
                'metallicFactor':0.,'roughnessFactor':.85}})
        for item in tree['meshes']:
            for primitive in item['primitives']:primitive['material']=index

    return export_glb(mesh,include_normals=True,buffer_postprocessor=colors_to_linear,tree_postprocessor=explicit_material)
