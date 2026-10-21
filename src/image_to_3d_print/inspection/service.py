import json,os,signal,subprocess,shutil
from pathlib import Path
from typing import Literal
import numpy as np
from pydantic import Field,StrictBool,StrictInt
from ..schemas.common import ContractModel,CheckResult,MeshInspection,PrinterProfile,Text,Id
from ..geometry.core import MeshStore,load_mesh,topology
from ..tools import ToolFailure,ToolSession,digest,stop_process_group

class InspectionConfig(ContractModel):
    blender: Path
    addon_dir: Path
    timeout_s: float=Field(default=120,gt=0,le=120)

class BedReview(ContractModel):
    mesh_version: Id
    confirmed: bool
    reviewer: Text
    origin: Literal['human','test_fixture']='human'

class ComponentReview(ContractModel):
    mesh_version: Id
    component_count: StrictInt=Field(ge=1)
    confirmed: StrictBool
    reviewer: Text
    origin: Literal['human','test_fixture']='human'

def blender_call(config,operation,mesh,directory,parameters=None):
    if config is None or not config.blender.is_file() or not (config.addon_dir/'object_print3d_utils/mesh_helpers.py').is_file():
        raise ToolFailure('TOOL_UNAVAILABLE','LinuxBlender或固定打印检查工具未配置')
    if os.name!='posix':raise ToolFailure('TOOL_UNAVAILABLE','本轮Blender适配仅验证Linux')
    lock=json.loads((Path(__file__).resolve().parents[3]/'locks/linux-geometry-tools.json').read_text(encoding='utf-8'))
    if digest(config.addon_dir/'object_print3d_utils/mesh_helpers.py')!=lock['print_toolbox']['sha256']:
        raise ToolFailure('TOOL_UNAVAILABLE','打印检查工具源码摘要与固定版本不符')
    payload={'vertices':mesh.vertices.tolist(),'faces':mesh.faces.tolist(),'parameters':parameters or {}}
    if operation=='preview' and mesh.visual.kind=='vertex':payload['vertex_colors']=mesh.visual.vertex_colors.tolist()
    (directory/'blender-input.json').write_text(json.dumps(payload,allow_nan=False),encoding='utf-8')
    worker=Path(__file__).resolve().parents[3]/'scripts/tools/blender_worker.py'
    argv=[str(config.blender),'--background','--factory-startup','--threads','4','--python',str(worker),'--',
        '--operation',operation,'--input',str(directory/'blender-input.json'),'--output',str(directory/'blender-result.json'),
        '--addon-dir',str(config.addon_dir)]
    watchdog=shutil.which('timeout')
    if watchdog is None:raise ToolFailure('TOOL_UNAVAILABLE','Linux缺少工具超时守护程序')
    argv=[watchdog,'--signal=TERM','--kill-after=5s',f'{config.timeout_s}s',*argv]
    with (directory/'blender.log').open('w',encoding='utf-8') as log:
        environment={**os.environ,'CUDA_VISIBLE_DEVICES':''}
        environment.pop('PYTHONPATH',None);environment.pop('PYTHONHOME',None)
        process=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=environment)
        try:code=process.wait(timeout=config.timeout_s)
        except subprocess.TimeoutExpired:
            stop_process_group(process);raise ToolFailure('TOOL_TIMEOUT','Blender检查超时，已终止本次进程组')
        except BaseException:
            stop_process_group(process)
            raise
    if code==124:raise ToolFailure('TOOL_TIMEOUT','Blender达到系统守护时限')
    if code:raise ToolFailure('TOOL_UNAVAILABLE','Blender检查失败，详见本任务日志')
    try:
        result=json.loads((directory/'blender-result.json').read_text(encoding='utf-8'))
        if result['operation']!=operation or result['blender_version']!='4.5.14':raise ValueError('工具或操作版本不符')
        return result
    except (OSError,ValueError,KeyError) as exc:raise ToolFailure('TOOL_UNAVAILABLE','Blender返回缺失或无效证据') from exc

def inspect_mesh(root,run,version,profile:PrinterProfile,height_mm=None,bed_review:BedReview|None=None,config=None,component_review:ComponentReview|None=None,*,automatic_bed=False):
    session=ToolSession(root,run,'inspect',version)
    try:
        source=MeshStore(root).get(run,version);mesh=load_mesh(Path(root)/source.relative_path);facts=topology(mesh)
        if source.parameters.get('printer_profile_id',profile.profile_id)!=profile.profile_id:
            raise ToolFailure('STATE_CONFLICT','打印检查配置与定标任务引用不一致')
        evidence_id=session.prefix+'_report';checks=[];engine='numpy1.26.4/trimesh4.0.5/geometry0.1'
        def check(name,status,value=None,threshold=None,unit=None,details=None,tool=engine):
            checks.append(CheckResult(name=name,status=status,value=value,threshold=threshold,unit=unit,
                tool_version=tool if status!='not_run' else None,evidence_artifact_id=evidence_id if status!='not_run' else None,details=details or {}))
        def missing(name,reason):check(name,'not_run',details={'reason':reason})
        check('finite_coordinates','pass',True)
        components_confirmed=(facts['component_count']==1 or component_review is not None and component_review.confirmed
            and component_review.mesh_version==version and component_review.component_count==facts['component_count'])
        check('components','pass' if components_confirmed else 'warn',facts['component_count'],1,'count',
            {'review':component_review.model_dump() if component_review else None,'reason':'分离组件须确认保留或指定删除，不能默认只留最大件'})
        for name,key in [('boundary_edges','boundary_edge_count'),('non_manifold_edges','non_manifold_edge_count'),('non_manifold_vertices','non_manifold_vertex_count')]:
            count=facts[key];check(name,'pass' if count==0 else 'fail',count,0)
        for name,key in [('watertight','watertight'),('normals','normals_consistent')]:check(name,'pass' if facts[key] else 'fail',facts[key],True)
        error=None;external=None
        try:
            external=blender_call(config,'inspect',mesh,session.directory,{'unit':source.unit,'min_wall_mm':profile.min_wall_mm})
            session.add('blender_evidence',session.directory/'blender-result.json','inspection_report',source.unit)
            tool='Blender4.5.14/print_toolbox@b42d6862'
            faces=external['self_intersection_faces'];check('self_intersection','fail' if faces else 'pass',len(faces),0,details={'face_indices':faces},tool=tool)
            if source.unit!='mm' or not facts['watertight'] or not facts['normals_consistent']:
                missing('wall_thickness','需要有效毫米尺度、水密且法线正确；不能将无命中当作通过')
            else:
                thin=external['thin_faces_low'];critical=external['thin_faces_high']
                if thin:check('wall_thickness','fail',{'thin_face_count':len(thin)},profile.min_wall_mm,'mm',{'face_indices':thin,'method':'six_seeded_inward_rays_per_face'},tool)
                elif critical:check('wall_thickness','warn',{'near_threshold_face_count':len(critical)},profile.min_wall_mm,'mm',{'face_indices':critical,'reason':'阈值附近±0.02毫米需复核'},tool)
                else:check('wall_thickness','pass',profile.min_wall_mm,profile.min_wall_mm,'mm',{'value_kind':'validated_sampling_lower_bound','sample_threshold_mm':profile.min_wall_mm+.02,'global_minimum_proven':False},tool)
            overhang=external['overhang_faces'];critical=external['critical_overhang_faces']
            check('overhang','warn' if overhang or critical else 'pass',len(overhang),45.,'degree',
                {'face_indices':overhang,'critical_face_indices':critical,'definition':'downward normal angle to -Z <45 degrees, bed faces excluded','supports':'human_slicer_review'},tool)
        except ToolFailure as exc:
            error=(exc.code,str(exc))
            for name in ['self_intersection','wall_thickness','overhang']:missing(name,str(exc))
        dimensions=mesh.extents.tolist() if source.unit=='mm' and all(mesh.extents>0) else None
        if dimensions is None or height_mm is None:missing('dimensions','需要确认高度与有效毫米网格')
        else:
            delta=abs(dimensions[2]-height_mm);tolerance=max(.5,height_mm*.01)
            check('dimensions','pass' if delta<=tolerance else 'fail',delta,tolerance,'mm',{'dimensions_mm':dimensions,'target_height_mm':height_mm})
        if dimensions is None or profile.build_volume_mm is None:missing('build_volume','打印空间或毫米外形未知')
        else:
            fits=bool(np.all(np.array(dimensions)<=np.array(profile.build_volume_mm)))
            check('build_volume','pass' if fits else 'fail',fits,profile.build_volume_mm,'mm',{'profile_kind':profile.profile_kind,'profile_version':profile.version})
        if source.unit!='mm':missing('bed_contact','需要毫米尺度和姿态确认')
        else:
            low=float(mesh.bounds[0,2]);touch=np.all(np.abs(mesh.vertices[mesh.faces][:,:,2])<=.01,axis=1)
            area=float(mesh.area_faces[touch].sum())
            positioned=abs(low)<=.01 and area>1e-6
            human=bed_review is not None and bed_review.mesh_version==version and bed_review.confirmed
            check('bed_contact','pass' if positioned and (human or automatic_bed) else 'warn' if positioned else 'fail',positioned,.01,'mm',
                {'contact_area_mm2':area,'minimum_z_mm':low,'human_review':bed_review.model_dump() if bed_review else None,
                 'origin':'automatic_policy' if automatic_bed else 'guided',
                 'reason':'自动几何触地检测；未执行实际切片/打印稳定性验证' if automatic_bed else '接触面积不等同稳定；需用户复核底面和支撑'})
        volume=facts['volume'] if source.unit=='mm' and external is not None and not external['self_intersection_faces'] else None
        inspection=MeshInspection(mesh_version=version,unit=source.unit,dimensions_mm=dimensions,
            volume_mm3=volume,volume_reason=None if volume is not None else '缺有效毫米实体、自交检查或方向证据',
            component_count=facts['component_count'],watertight=facts['watertight'],normals_consistent=facts['normals_consistent'],
            boundary_edge_count=facts['boundary_edge_count'],non_manifold_edge_count=facts['non_manifold_edge_count'],
            non_manifold_vertex_count=facts['non_manifold_vertex_count'],checks=checks)
        verdict=('blocked' if any(c.status in {'fail','not_run'} for c in checks) else
            'needs_review' if any(c.status=='warn' and c.name!='overhang' for c in checks) else
            'ready_for_slicer' if inspection.ready_for_print else 'needs_review')
        data={'inspection':inspection.model_dump(mode='json'),'verdict':verdict,'task_success':False,'source_sha256':source.sha256}
        if (session.directory/'blender.log').exists():session.add('blender_log',session.directory/'blender.log','log')
        return session.fail(*error,data=data) if error else session.finish(data)
    except ToolFailure as exc:return session.fail(exc.code,str(exc))

def preview_mesh(root,run,version,config):
    session=ToolSession(root,run,'inspect',version)
    try:
        source=MeshStore(root).get(run,version);mesh=load_mesh(Path(root)/source.relative_path)
        if len(mesh.faces)>500000:raise ToolFailure('INVALID_ARGUMENT','超大原始网格先生成受控简化提案，预览不自动删面')
        result=blender_call(config,'preview',mesh,session.directory,{'unit':source.unit})
        session.add('preview',session.directory/'preview.png','inspection_report')
        return session.finish({'mesh_version':version,'unit':source.unit,'geometry_preview':True,'render_device':'CPU','printing_pass':False,'renderer':result})
    except ToolFailure as exc:return session.fail(exc.code,str(exc))
