"""近表面UV/PBR转移：复用贴图字节，不烘焙，不修改最终修复几何。"""
import copy
from pathlib import Path
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from ..geometry.glb_preserve import GLBDocument,display_matrix
from ..geometry.appearance import smooth_vertex_normals
from ..tools import ToolFailure


def reproject_pbr(source,mesh,output,max_distance_mm=2.):
    if Path(output).exists() or Path(source).resolve()==Path(output).resolve():
        raise ToolFailure('STATE_CONFLICT','彩色输出不能覆盖原件或已有文件')
    doc=GLBDocument(source);signature=doc.material_signature()
    if not doc.has_uv or not doc.tree.get('images'):
        raise ToolFailure('INVALID_ARGUMENT','源网格缺少UV/彩色贴图，不能冒充彩色PBR交付')
    positions=trimesh.transform_points(doc.positions,doc.logical_matrix)
    faces=[];uvs=[];groups=[];offset=0
    for index,p in enumerate(doc.primitives):
        if 'TEXCOORD_0' not in p['attributes'] or 'material' not in p or 'COLOR_0' in p['attributes']:
            raise ToolFailure('INVALID_ARGUMENT','当前彩色转移需要普通UV/PBR，不支持缺UV或混合顶点色来源')
        material=doc.tree['materials'][p['material']]
        if 'baseColorTexture' not in material.get('pbrMetallicRoughness',{}):
            raise ToolFailure('INVALID_ARGUMENT','原材质缺少彩色贴图，不能伪造纹理来源')
        for channel in [material.get('pbrMetallicRoughness',{}),material]:
            if any(isinstance(v,dict) and 'index' in v and (v.get('texCoord',0)!=0 or v.get('extensions')) for v in channel.values()):
                raise ToolFailure('INVALID_ARGUMENT','不支持源材质的额外UV通道或纹理变换')
        local=doc.faces(p);faces.append(local+offset)
        uv=doc.accessor(p['attributes']['TEXCOORD_0']).astype(float)
        a=doc.tree['accessors'][p['attributes']['TEXCOORD_0']]
        if a.get('normalized'):uv/=np.iinfo(doc.accessor(p['attributes']['TEXCOORD_0']).dtype).max
        if uv.shape[1]!=2 or not np.isfinite(uv).all():raise ToolFailure('INVALID_ARGUMENT','源UV无效')
        uvs.append(uv[local]);groups.extend([index]*len(local))
        offset+=doc.tree['accessors'][p['attributes']['POSITION']]['count']
    triangles=positions[np.vstack(faces)];uv_tri=np.vstack(uvs);groups=np.asarray(groups)
    normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);length=np.linalg.norm(normals,axis=1)
    valid=length>1e-10
    if not valid.any():raise ToolFailure('INVALID_ARGUMENT','源网格没有有效三角面')
    triangles=triangles[valid];uv_tri=uv_tri[valid];groups=groups[valid];normals=normals[valid]/length[valid,None]
    tree=cKDTree(triangles.mean(axis=1));target_faces=np.asarray(mesh.faces);target=np.asarray(mesh.vertices)[target_faces]
    target_normals=np.asarray(mesh.face_normals);mapped=[];chosen=[];distances=[]
    # 每个目标面使用同一源三角形的UV片，避免直接跨UV岛连接产生色带。
    for start in range(0,len(target),4096):
        batch=target[start:start+4096];centers=batch.mean(axis=1);k=min(12,len(triangles))
        _,near=tree.query(centers,k=k);near=np.asarray(near).reshape(len(batch),k)
        sample=np.repeat(centers,k,axis=0);nearest=trimesh.triangles.closest_point(triangles[near.reshape(-1)],sample)
        distance=np.linalg.norm(nearest-sample,axis=1).reshape(len(batch),k)
        dot=np.einsum('ijk,ik->ij',normals[near],target_normals[start:start+len(batch)])
        rank=distance+(dot<0)*max_distance_mm*2
        pick=near[np.arange(len(batch)),rank.argmin(axis=1)]
        distances.extend(distance[np.arange(len(batch)),rank.argmin(axis=1)].tolist())
        corners=trimesh.triangles.closest_point(np.repeat(triangles[pick],3,axis=0),batch.reshape(-1,3))
        bary=trimesh.triangles.points_to_barycentric(np.repeat(triangles[pick],3,axis=0),corners)
        bary=np.clip(bary,0,1);bary/=bary.sum(axis=1,keepdims=True)
        mapped.append(np.einsum('ij,ijk->ik',bary,np.repeat(uv_tri[pick],3,axis=0)).reshape(-1,3,2));chosen.extend(pick.tolist())
    distances=np.asarray(distances)
    if not np.isfinite(distances).all() or distances.max()>max_distance_mm:
        raise ToolFailure('INVALID_ARGUMENT','最终修复几何与贴图源距离过大，拒绝不可靠颜色对应')
    mapped=np.vstack(mapped);chosen=np.asarray(chosen);matrix=display_matrix('mm')
    display=trimesh.transform_points(np.asarray(mesh.vertices),matrix)
    normals_out=smooth_vertex_normals(mesh)@np.linalg.inv(matrix[:3,:3])
    normals_out/=np.linalg.norm(normals_out,axis=1,keepdims=True)
    primitives=[]
    for index,source_p in enumerate(doc.primitives):
        selected=np.flatnonzero(groups[chosen]==index)
        if not len(selected):continue
        ids=target_faces[selected].reshape(-1);p=copy.deepcopy(source_p)
        p['attributes']={'POSITION':doc.append(display[ids],'VEC3'),'NORMAL':doc.append(normals_out[ids],'VEC3'),
            'TEXCOORD_0':doc.append(mapped[selected].reshape(-1,2),'VEC2')}
        p['indices']=doc.append(np.arange(len(ids),dtype=np.uint32).reshape(-1,1),'SCALAR',5125)
        p.pop('extras',None);primitives.append(p)
    doc.tree['meshes'][0]['primitives']=primitives
    doc.tree.setdefault('extras',{})['i3d']={'logical_from_gltf':np.linalg.inv(matrix).tolist(),'unit':'mm','frame':'z_up','appearance':'pbr_surface_reprojection'}
    doc.save(output);reread=GLBDocument(output)
    if reread.material_signature()!=signature:raise ToolFailure('STATE_CONFLICT','颜色转移改变了原材质/贴图字节')
    from ..geometry.core import load_mesh
    from ..geometry.glb_preserve import _keys
    checked=load_mesh(output);distance,mapping=cKDTree(np.asarray(mesh.vertices)).query(checked.vertices)
    if (distance.max()>.01 or len(checked.faces)!=len(mesh.faces)
            or not np.array_equal(np.sort(_keys(np.asarray(mesh.faces))),np.sort(_keys(mapping[np.asarray(checked.faces)])))):
        raise ToolFailure('STATE_CONFLICT','彩色GLB独立读回三角形与最终修复几何不一致')
    return {'status':'print_pbr_reprojected','policy_version':'print-pbr-reproject-v1','pbr_available':True,
        'rebaked':False,'approximation':True,'source_images_sha256':signature['images_sha256'],
        'max_centroid_distance_mm':float(distances.max()),'p95_centroid_distance_mm':float(np.quantile(distances,.95)),
        'max_allowed_distance_mm':max_distance_mm,'source_faces':len(triangles),'target_faces':len(target_faces),'independent_triangle_correspondence':True,
        'warning':'最终修复几何复用原贴图/PBR，UV按近表面对应重建；补洞/加厚位置的颜色为近似，未重烘焙。'}
