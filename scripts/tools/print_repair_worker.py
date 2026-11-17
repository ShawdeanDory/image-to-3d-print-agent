"""简单展示件的隔离CPU原生算法；不导入重建模型，不保留旧输出。"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import numpy as np
import trimesh
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from image_to_3d_print.geometry.print_components import finish_components,main_component


def close_shells(mesh,folder,policy='legacy'):
    import pymeshfix
    from meshlib import mrmeshpy as mm
    vertices,faces=pymeshfix.clean_from_arrays(np.asarray(mesh.vertices,dtype=np.float64),
        np.asarray(mesh.faces,dtype=np.int32),verbose=False,joincomp=False,remove_smallest_components=False)
    fixed=trimesh.Trimesh(vertices,faces,process=False)
    parts=list(fixed.split(only_watertight=False,repair=policy=='legacy'))
    if not parts or len(parts)>(2048 if policy=='wall05-components-v2' else 16) or not all(p.is_watertight for p in parts):
        raise ValueError('MeshFix后仍非闭合或组件过多，不删除未知部件')
    native=[]
    for i,part in enumerate(parts):
        file=folder/f'closed-part-{i}.stl';part.export(file);native.append(mm.loadMesh(str(file)))
    inside=[]
    for i,part in enumerate(parts):
        containers=[]
        for j,outer in enumerate(parts):
            if i==j or abs(outer.volume)<=abs(part.volume):continue
            if np.all(part.bounds[0]>outer.bounds[0]) and np.all(part.bounds[1]<outer.bounds[1]):
                if mm.isInside(mm.MeshPart(native[i]),mm.MeshPart(native[j])):containers.append(j)
        if containers:inside.append({'component':i,'contained_by':containers,'faces':len(part.faces),
            'signed_volume_mm3':float(part.volume),'method':'MeshLib.isInside_closed_mesh'})
    outer=[part for i,part in enumerate(parts) if i not in {x['component'] for x in inside}]
    if not outer:raise ValueError('没有有效外部主体')
    if len(outer)!=1 and policy=='legacy':raise ValueError('存在多个外部独立部件，拒绝默认只保留最大件')
    result=trimesh.util.concatenate(outer);trimesh.repair.fix_normals(result,multibody=True)
    return result,{'algorithm':'MeshFix+closed_shell_containment','meshfix':pymeshfix.__version__,
        'joincomp':False,'remove_smallest_components':False,'filled_internal_cavities':inside,
        'external_components_kept':len(outer),'not_original_uv':True,'policy':policy,
        'removed_external_components':[]}


def compensate(mesh,folder,thin,bed,min_wall,height,policy='legacy'):
    from meshlib import mrmeshpy as mm
    file=folder/'input-mm.stl';mesh.export(file);native=mm.loadMesh(str(file))
    modern=policy=='wall05-components-v2'
    multiple=modern and main_component(mesh)[1]['component_count']>1
    offset=thin or multiple
    radius=min_wall/2+.1 if offset else 0.
    if radius>.8:raise ValueError('本轮展示件只允许≤0.8mm的有限厚度补偿')
    facts={'algorithm':'MeshLib bounded offset/plane cut/local self-intersection repair',
        'offset_mm':radius,'voxel_mm':None,'bed_cut_mm':0.,'rebaked':False,'not_original_uv':True}
    facts.update(policy=policy,offset_scope='whole_print_copy' if offset else 'none',
        fusion_attempted=bool(multiple))
    if offset:
        voxel=.2 if modern else .35
        # 有限体素分辨率仍需最终厚度复检；不把偏移距离当成实测最小壁厚。
        if modern and np.prod(np.ceil((mesh.extents+radius*2)/voxel))>150000000:
            raise ValueError('有界包裹体素数量超限，保留输入及失败记录')
        params=mm.GeneralOffsetParameters();params.voxelSize=voxel
        params.signDetectionMode=mm.SignDetectionMode.HoleWindingRule;params.closeHolesInHoleWindingNumber=True
        native=mm.generalOffsetMesh(mm.MeshPart(native),radius,params)
        decimate=mm.DecimateSettings();decimate.maxError=.02 if modern else .06
        decimate.maxDeletedFaces=max(0,native.topology.numValidFaces()-100000);mm.decimateMesh(native,decimate)
        facts.update(voxel_mm=voxel,decimate_max_error_mm=decimate.maxError)
    if modern:
        complete=folder/'after-fusion.stl';mm.saveMesh(native,str(complete))
        complete_mesh=trimesh.load(complete,force='mesh',process=False)
        retained,components=finish_components(complete_mesh,folder,phase=2)
        facts['components']=components
        selected=folder/'retained-body.stl';retained.export(selected);native=mm.loadMesh(str(selected))
    if bed or offset:
        params=mm.TrimWithPlaneParams();params.plane=mm.Plane3f(mm.Vector3f(0,0,1),float(native.computeBoundingBox().min.z)+.5)
        mm.trimWithPlane(native,params)
        loops=mm.findRightBoundary(native.topology)
        if len(loops)!=1:raise ValueError('底部切口不是单闭环，不自动添加底座或猜测多个切口')
        mm.fillHole(native,loops[0][0]);facts['bed_cut_mm']=.5
    intermediate=folder/'resampled.stl';mm.saveMesh(native,str(intermediate));result=trimesh.load(intermediate,force='mesh',process=False)
    result.apply_scale(height/result.extents[2]);result.apply_translation([0,0,-result.bounds[0,2]])
    scaled=folder/'scaled.stl';result.export(scaled);native=mm.loadMesh(str(scaled))
    before=len(mm.findSelfCollidingTriangles(mm.MeshPart(native)))
    if before:
        settings=mm.SelfIntersections.Settings();settings.method=mm.SelfIntersections.Settings.Method.CutAndFill
        settings.maxExpand=2;settings.relaxIterations=0;settings.mimicPatch=False
        mm.localFixSelfIntersections(native,settings)
    after=len(mm.findSelfCollidingTriangles(mm.MeshPart(native)))
    facts.update(native_intersection_pairs_before=before,native_intersection_pairs_after=after)
    if after:raise ValueError('局部切口修复后仍存在自交')
    final=folder/'native-final.stl';mm.saveMesh(native,str(final))
    result=trimesh.load(final,force='mesh',process=False);trimesh.repair.fix_normals(result,multibody=True)
    if modern and main_component(result)[1]['component_count']>1:
        last=folder/'post-local-repair';last.mkdir()
        result,removal=finish_components(result,last,phase=2)
        facts['post_local_components']=removal
    return result,facts


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',type=Path,required=True);args=parser.parse_args()
    req=json.loads(args.request.read_text(encoding='utf-8'));allowed={'input','output','native_paths','phase','thin','bed','min_wall','height'}
    if not allowed<=set(req) or set(req)-allowed-{'policy'} or type(req['phase'])!=int or req['phase'] not in {1,2}:raise ValueError('未知原生算法参数')
    policy=req.get('policy','legacy')
    if policy not in {'legacy','wall05-components-v2'}:raise ValueError('未知打印修复政策')
    if policy=='wall05-components-v2' and req['min_wall']!=.5:raise ValueError('新政策必须配合0.5mm打印配置')
    folder=args.request.resolve().parent;source=Path(req['input']).resolve();target=Path(req['output']).resolve()
    if source.parent!=folder or target.parent!=folder or target.exists():raise ValueError('文件不属于本轮目录或已有输出')
    if not 100<=req['height']<=150 or not 0<req['min_wall']<=1.4:raise ValueError('超出本轮小摆件参数范围')
    for path in reversed(req['native_paths']):
        if not Path(path).is_dir():raise ValueError('原生依赖目录不存在')
        sys.path.insert(0,path)
    versions={n:importlib.metadata.version(n) for n in ['pymeshfix','meshlib-core']}
    if versions!={'pymeshfix':'0.18.1','meshlib-core':'3.1.4.297'}:raise ValueError('修复工具版本未锁定')
    data=np.load(source,allow_pickle=False);v=data['vertices'];f=data['faces']
    if v.ndim!=2 or v.shape[1]!=3 or not len(v) or not np.isfinite(v).all() or f.ndim!=2 or f.shape[1]!=3 or not 0<len(f)<=5000000 or f.min()<0 or f.max()>=len(v):raise ValueError('网格输入无效')
    mesh=trimesh.Trimesh(v,f,process=False)
    out,facts=close_shells(mesh,folder,policy) if req['phase']==1 else compensate(mesh,folder,req['thin'],req['bed'],req['min_wall'],req['height'],policy)
    np.savez(target,vertices=np.asarray(out.vertices),faces=np.asarray(out.faces))
    facts.update(versions=versions,input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),output_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    (folder/'native-result.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
