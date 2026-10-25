"""从已保存原GLB恢复已检查副本的UV/PBR；仅CPU文件操作，不生成模型。"""
import argparse,hashlib,json,pathlib,shutil,sys
import numpy as np
import trimesh
from scipy.spatial import cKDTree
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'src'))
from image_to_3d_print.geometry.glb_preserve import GLBDocument,preserve_glb,display_matrix,_keys
from image_to_3d_print.geometry.core import load_mesh


def verify(source,output,expected,matrix):
    a,b=GLBDocument(source),GLBDocument(output)
    if a.material_signature()!=b.material_signature():raise ValueError('材质/贴图字节不一致')
    actual=load_mesh(output)
    tolerance=max(float(expected.extents.max())*1e-6,1e-5)
    distances,ids=cKDTree(expected.vertices).query(actual.vertices)
    if (distances.max()>tolerance or cKDTree(actual.vertices).query(expected.vertices)[0].max()>tolerance
            or len(actual.faces)!=len(expected.faces)
            or not np.array_equal(np.sort(_keys(ids[actual.faces])),np.sort(_keys(expected.faces)))):
        raise ValueError('恢复材质改变了已检查几何')
    # 独立按每个材质primitive检查：几何位置+UV/颜色的角点组合必须来自原面。
    offset=0
    for old,new in zip(a.primitives,b.primitives):
        pos=trimesh.transform_points(a.accessor(old['attributes']['POSITION']),matrix)
        geom,orig_ids=np.unique(pos,axis=0,return_inverse=True)
        target=trimesh.transform_points(b.accessor(new['attributes']['POSITION']),b.logical_matrix)
        distance,target_ids=cKDTree(geom).query(target)
        if distance.max()>tolerance:raise ValueError('材质顶点位置无原件对应')
        source_columns=[orig_ids[:,None]];target_columns=[target_ids[:,None]]
        for attr in old['attributes']:
            if attr not in {'POSITION','NORMAL','TANGENT'}:
                source_columns.append(a.accessor(old['attributes'][attr]))
                target_columns.append(b.accessor(new['attributes'][attr]))
        source_values=np.ascontiguousarray(np.hstack(source_columns),dtype='<f8')
        target_values=np.ascontiguousarray(np.hstack(target_columns),dtype='<f8')
        dtype=np.dtype([(f'x{i}','<f8') for i in range(source_values.shape[1])])
        unique,first=np.unique(source_values.view(dtype).reshape(-1),return_inverse=True)
        new_keys=target_values.view(dtype).reshape(-1);mapped=np.searchsorted(unique,new_keys)
        valid=(mapped<len(unique));mapped=np.minimum(mapped,len(unique)-1);valid&=unique[mapped]==new_keys
        old_faces=a.faces(old);new_faces=b.faces(new)
        faces=_keys(first[old_faces]);restored=_keys(mapped[new_faces])
        bad=np.flatnonzero(~np.isin(restored,faces)|~valid[new_faces].all(axis=1))
        if len(bad):
            # 浮点量化后的近邻可能不唯一；对这些面逐一验证实际原角点，不放宽UV。
            import itertools
            tree=cKDTree(pos);candidates=tree.query_ball_point(target[new_faces[bad,0]],tolerance)
            needed=set(v for row in candidates for v in row)
            selected_rows=np.flatnonzero(np.isin(old_faces,list(needed)).any(axis=1))
            adjacency={v:[] for v in needed}
            for row in selected_rows:
                for v in old_faces[row]:
                    if int(v) in adjacency:adjacency[int(v)].append(int(row))
            for face_index,nearby in zip(bad,candidates):
                target_face=new_faces[face_index];candidate_rows=set(r for v in nearby for r in adjacency[v]);found=False
                for row in candidate_rows:
                    for order in itertools.permutations(range(3)):
                        original_face=old_faces[row,list(order)]
                        if (np.linalg.norm(pos[original_face]-target[target_face],axis=1).max()<=tolerance
                                and np.array_equal(source_values[original_face,1:],target_values[target_face,1:])):
                            found=True;break
                    if found:break
                if not found:raise ValueError('UV角点/颜色与原始几何配对不一致')
        if old.get('material')!=new.get('material'):raise ValueError('面材质归属改变')
    return {'checked_face_count':len(actual.faces),'geometry_unchanged':True,'max_mm_error':float(distances.max()),
        'uv_corner_material_pairs_match_original':True,'materials_and_images_identical':True,
        'image_sha256':a.material_signature()['images_sha256'],'has_pbr_textures':bool(a.tree.get('images'))}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=pathlib.Path,required=True)
    args=parser.parse_args();out=args.directory.resolve()
    data=json.loads((out/'viewer-data.json').read_text(encoding='utf-8'))
    backup=out/'normals-linear-v2';backup.mkdir(exist_ok=True)
    if not (backup/'index.html').exists():shutil.copyfile(out/'index.html',backup/'index.html')
    report=[]
    for task in data['selected']:
        original=out/task['files']['original']['local'];copy=out/task['files']['copy']['local']
        for role,path in [('original',original),('copy',copy)]:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=task[role+'_sha256']:raise ValueError('源摘要改变')
        version=json.loads((out/task['files']['version']['local']).read_text(encoding='utf-8'))
        rotation=trimesh.transformations.rotation_matrix(np.pi/2,[1,0,0]) if task['original_frame']=='y_up' else np.eye(4)
        matrix=np.asarray(version['parameters']['matrix'])@rotation
        mesh=trimesh.load(copy,force='mesh',process=False)
        output=copy.with_name('inspection-pbr.glb')
        if output.exists():
            facts={k:v for k,v in GLBDocument(output).tree['extras']['i3d'].items() if k not in {'logical_from_gltf','unit','frame'}}
        else:facts=preserve_glb(original,mesh,output,source_to_logical=matrix,logical_to_output=display_matrix('mm'),unit='mm')
        verified=verify(original,output,mesh,matrix)
        task['copy_view']=output.relative_to(out).as_posix();task['copy_appearance']='original_pbr' if verified['has_pbr_textures'] else 'original_vertex_color'
        task['copy_derived_note']='已检查几何保持，逐角UV/材质/嵌入贴图原样恢复；GLB为米/Y朝上，逻辑检查为毫米/Z朝上；不重建、不烘焙。'
        row={'index':task['index'],'run_id':task['run_id'],'file':task['copy_view'],'preservation':facts,'verification':verified}
        report.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    data['display_revision']='pbr-preserved-v3'
    (out/'viewer-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'pbr-restoration.json').write_text(json.dumps({'policy':'glb-preserve-v1','model_runs':0,'rebakes':0,'results':report},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
