"""单件10～15cm展示摆件的独立打印转换；不改生产工作流或原始彩色GLB。"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4
import numpy as np
import trimesh
from pydantic import Field
from .schemas.common import ContractModel,PrinterProfile,MeshInspection
from .schemas.task import ModelTaskRequest
from .jobs.config import Settings
from .tools import ToolFailure,ToolSession,digest,stop_process_group
from .geometry.core import MeshStore,load_mesh,topology
from .geometry.glb_preserve import prepare_inspection_glb,write_plain_glb
from .geometry.structure import preservation
from .inspection.service import inspect_mesh,blender_call


class PrintDemoConfig(ContractModel):
    native_python:Path
    native_paths:list[Path]=Field(min_length=1,max_length=4)
    timeout_s:float=Field(default=180,gt=0,le=300)


def shape_gate(before,after):
    facts=preservation(before,after)
    return {'three_view_iou':facts['fixed_three_view_iou'],'max_relative_dimension_change':facts['max_relative_dimension_change'],
        'accepted':min(facts['fixed_three_view_iou'])>=.97 and facts['max_relative_dimension_change']<=.02,
        'scope':'固定三正交方向轮廓/尺寸，不是有真值的三维还原误差'}


def gcode_summary(content,height,layer_height=None,supports=False):
    heights=[float(m.group(1)) for m in re.finditer(r'^;Z:([+\-0-9.eE]+)$',content,re.M)]
    layers=content.count(';LAYER_CHANGE');extrusion=False
    for line in content.splitlines():
        amount=re.search(r'\bE([+\-0-9.eE]+)',line)
        if line.startswith('G1 ') and re.search(r'\b[XY][+\-0-9.]',line) and amount and float(amount.group(1))>0:extrusion=True
    valid=bool(len(heights)>=2 and all(np.isfinite(heights)) and all(a<b for a,b in zip(heights,heights[1:])))
    correct=valid and abs(heights[-1]-height)<=.25 and layers==len(heights)
    if layer_height is not None:
        expected=round(height/layer_height)
        # 支撑可插入中间Z层，不能把模型的名义600层当作全部工具路径层数。
        count_ok=(expected<=layers<=expected*2+2) if supports else abs(layers-expected)<=1
        correct=correct and count_ok and all(b-a<=layer_height+.001 for a,b in zip(heights,heights[1:]))
    return {'passed':bool(correct and extrusion),'layers':layers,'first_z_mm':heights[0] if heights else None,
        'last_z_mm':heights[-1] if heights else None,'has_extrusion_moves':extrusion,'physical_print':False}


def native_call(mesh,directory,phase,config,inspection,height,min_wall):
    if os.name!='posix' or not config.native_python.is_file():raise ToolFailure('TOOL_UNAVAILABLE','打印修复需要已配置的Linux原生工具')
    input=directory/'input.npz';output=directory/'output.npz';np.savez(input,vertices=mesh.vertices,faces=mesh.faces)
    states={c.name:c.status for c in inspection.checks};request={'input':str(input),'output':str(output),
        'native_paths':[str(p) for p in config.native_paths],'phase':phase,'thin':states.get('wall_thickness')=='fail',
        'bed':states.get('bed_contact')=='fail','height':height,'min_wall':min_wall}
    file=directory/'request.json';file.write_text(json.dumps(request),encoding='utf-8')
    worker=Path(__file__).resolve().parents[2]/'scripts/tools/print_repair_worker.py'
    environment={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'4'};environment.pop('PYTHONPATH',None);environment.pop('PYTHONHOME',None)
    with (directory/'native.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([str(config.native_python),str(worker),'--request',str(file)],stdout=log,stderr=subprocess.STDOUT,
            start_new_session=True,env=environment)
        try:code=process.wait(timeout=config.timeout_s)
        except subprocess.TimeoutExpired:stop_process_group(process);raise ToolFailure('TOOL_TIMEOUT','原生打印修复超时，已停止本轮进程组')
        except BaseException:stop_process_group(process);raise
    if code:raise ToolFailure('TOOL_UNAVAILABLE','原生打印修复失败，保留本轮日志和之前版本')
    facts=json.loads((directory/'native-result.json').read_text(encoding='utf-8'))
    if facts['input_sha256']!=digest(input) or facts['output_sha256']!=digest(output):raise ToolFailure('STATE_CONFLICT','原生修复输入输出摘要不符')
    data=np.load(output,allow_pickle=False);candidate=trimesh.Trimesh(data['vertices'],data['faces'],process=False)
    if not len(candidate.faces) or not np.isfinite(candidate.vertices).all():raise ToolFailure('INVALID_ARGUMENT','修复网格为空或坐标无效')
    return candidate,facts


def prepare_demo(source,output,settings,config,height=120.,frame='y_up'):
    source=Path(source).resolve();root=Path(output).resolve()
    if source.suffix.lower()!='.glb' or not source.is_file() or not 100<=height<=150:
        raise ToolFailure('INVALID_ARGUMENT','仅接受已有GLB和100～150mm展示高度')
    if root.exists():raise ToolFailure('STATE_CONFLICT','输出目录已存在，不能覆盖历史模型')
    root.mkdir(parents=True);before_sha=digest(source);original=root/'original-color.glb';original.write_bytes(source.read_bytes())
    prepared=root/'inspection-input.glb';prepare_inspection_glb(original,prepared,frame)
    run=uuid4();store=MeshStore(root);raw=store.import_mesh(prepared.relative_to(root).as_posix(),run)
    profile=PrinterProfile.model_validate_json(settings.profile_files[0].read_text(encoding='utf-8'))
    request=ModelTaskRequest(image_asset_id='existing_generated_glb',printer_profile_id=profile.profile_id,height_value=height,
        height_unit='mm',scale_source='user_target',orientation={'up_axis':'z','confirmed':False})
    scaled=store.scale(run,raw.mesh_version,request,automatic_orientation=True)
    if not scaled.tool.succeeded:raise ToolFailure(scaled.tool.error.code,scaled.tool.error.message)
    version=store.get(run,scaled.tool.data['mesh_version']);source_mesh=load_mesh(root/version.relative_path)
    session=ToolSession(root,run,'repair',raw.mesh_version);session.add('original',original,'raw_mesh','unitless')
    all_outcomes=[];history=[];rounds=[]
    for phase in range(3):
        checked=inspect_mesh(root,run,version.mesh_version,profile,height,config=settings.tools.inspection,automatic_bed=True)
        all_outcomes.append(checked)
        if not checked.tool.succeeded:raise ToolFailure(checked.tool.error.code,checked.tool.error.message)
        inspection=MeshInspection.model_validate(checked.tool.data['inspection']);history.append(inspection.model_dump(mode='json'))
        if inspection.ready_for_print or phase==2:break
        folder=session.directory/f'round-{phase+1}';folder.mkdir()
        mesh=load_mesh(root/version.relative_path);candidate,facts=native_call(mesh,folder,phase+1,config,inspection,height,profile.min_wall_mm)
        shape=shape_gate(source_mesh,candidate);record={'round':phase+1,'method':facts,'shape':shape};rounds.append(record)
        (folder/'acceptance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        if not shape['accepted']:raise ToolFailure('INVALID_ARGUMENT','打印修复改变外形超出门槛；候选保留但不交付为通过')
        native_glb=folder/'print-copy.glb';write_plain_glb(candidate,native_glb,'mm')
        reread=load_mesh(native_glb)
        if len(reread.faces)!=len(candidate.faces) or not np.allclose(reread.extents,candidate.extents,atol=.01):
            raise ToolFailure('INVALID_ARGUMENT','打印GLB独立读回不一致')
        version=store._write(run,candidate,'mm','print_demo_repair',version.mesh_version,
            {'print_demo_policy':'print-demo-v1','round':record,'source_sha256':before_sha},phase+1,original_path=native_glb)
    mesh=load_mesh(root/version.relative_path);session.mesh_version=version.mesh_version
    stl=root/f'duck-print-{height:g}mm.stl';mesh.export(stl);glb=root/f'duck-print-{height:g}mm.glb';glb.write_bytes((root/version.relative_path).read_bytes())
    if not np.allclose(load_mesh(stl).extents,mesh.extents,atol=.01):raise ToolFailure('INVALID_ARGUMENT','打印STL独立读回不一致')
    session.add('stl',stl,'candidate_stl','mm');session.add('glb',glb,'repaired_mesh','mm')
    if digest(source)!=before_sha or digest(original)!=before_sha:raise ToolFailure('STATE_CONFLICT','原始GLB摘要改变')
    preview=session.directory/'preview';preview.mkdir();blender_call(settings.tools.inspection,'preview',mesh,preview,{'unit':'mm'})
    session.add('preview',preview/'preview.png','inspection_report')
    outcome=session.finish({'policy':'print-demo-v1','mesh_version':version.mesh_version,'dimensions_mm':mesh.extents.tolist(),
        'faces':len(mesh.faces),'repair_attempts':len(rounds),'ready_for_slicing':inspection.ready_for_print,
        'inspection':inspection.model_dump(mode='json'),'inspection_history':history,'rounds':rounds,
        'source_sha256':before_sha,'original_unchanged':True,'appearance':'print_geometry_copy_without_original_uv',
        'rebaked':False,'physical_print':False,'new_model_calls':0,'llm_calls':0,
        'warning':'打印副本可填实内腔、有限厚度补偿和切平底部，未保留原UV/PBR；原始彩色GLB另存。悬垂需支撑，实际打印待设备核对。'})
    for previous in all_outcomes:
        outcome.artifacts.extend(previous.artifacts);outcome.evidence.extend(previous.evidence)
    (root/'result.json').write_text(outcome.model_dump_json(indent=2)+'\n',encoding='utf-8')
    return outcome


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--settings',type=Path,required=True);parser.add_argument('--native-config',type=Path,required=True)
    parser.add_argument('--height-mm',type=float,default=120);parser.add_argument('--frame',choices=['y_up','z_up'],default='y_up');args=parser.parse_args()
    try:
        result=prepare_demo(args.source,args.output,Settings.model_validate_json(args.settings.read_text(encoding='utf-8')),
            PrintDemoConfig.model_validate_json(args.native_config.read_text(encoding='utf-8')),args.height_mm,args.frame)
    except (ToolFailure,OSError,ValueError) as exc:
        print(json.dumps({'succeeded':False,'error':{'code':exc.code if isinstance(exc,ToolFailure) else 'INVALID_ARGUMENT','message':str(exc)}},ensure_ascii=False))
        raise SystemExit(2)
    print(json.dumps({'run_id':str(result.tool.run_id),'ready_for_slicing':result.tool.data['ready_for_slicing'],'physical_print':False}))
    if not result.tool.data['ready_for_slicing']:raise SystemExit(2)


if __name__=='__main__':main()
