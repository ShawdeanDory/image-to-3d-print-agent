"""在同一原始网格上运行固定后处理，与已完成Agent轨迹对照；不重复重建或调用LLM。"""
import argparse,json,sys,time
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from image_to_3d_print.jobs.store import Store
from image_to_3d_print.jobs.config import Settings
from image_to_3d_print.geometry.core import MeshStore,load_mesh,topology
from image_to_3d_print.inspection.service import inspect_mesh,preview_mesh,BedReview,ComponentReview
from image_to_3d_print.schemas import PrinterProfile,ModelTaskRequest
from image_to_3d_print.tools import digest

def compare(settings,run):
    store=Store(settings.root);ctx=store.row(run)['context'];meshstore=MeshStore(settings.root)
    generated=[op for op in ctx['operations'] if op['operation']=='reconstruct']
    if len(generated)!=1:raise ValueError('必须恰有一次真实重建，不能选择多个结果中的最好值')
    rawdata=generated[0]['result']['data'];source=meshstore.get(run,rawdata['mesh_version'])
    source_path=settings.root/source.relative_path;original_sha=digest(source_path)
    request=ModelTaskRequest.model_validate(ctx['request'])
    if request.pending_inputs:raise ValueError('固定流程缺少明确约束，拒绝猜测尺寸')
    target=str(uuid4());raw=meshstore.import_mesh(source.relative_path,target,source.unit,
        {'backend':ctx['backend'],'comparison_source_run':run,'comparison_sha256':original_sha})
    start=time.perf_counter();timings={};results={}
    def step(name,fn):
        begin=time.perf_counter();outcome=fn();timings[name]=time.perf_counter()-begin
        results[name]=outcome.model_dump(mode='json')
        if not outcome.tool.succeeded:raise RuntimeError(name+'失败：'+str(outcome.tool.error))
        return outcome.tool.data
    clean=step('clean',lambda:meshstore.clean(target,raw.mesh_version))
    scale=step('scale',lambda:meshstore.scale(target,clean['mesh_version'],request));version=scale['mesh_version']
    step('preview',lambda:preview_mesh(settings.root,target,version,settings.tools.inspection))
    inspected=step('inspect',lambda:inspect_mesh(settings.root,target,version,PrinterProfile.model_validate(ctx['profile']),request.height_mm,
        BedReview(mesh_version=version,confirmed=True,reviewer='comparison_fixture',origin='test_fixture'),settings.tools.inspection,
        ComponentReview(mesh_version=version,component_count=ctx['inspection']['component_count'],confirmed=True,reviewer='comparison_fixture',origin='test_fixture')))
    actual=ctx['inspection'];direct=inspected['inspection'];old=topology(load_mesh(source_path))
    a={c['name']:(c['status'],c['value']) for c in actual['checks']};b={c['name']:(c['status'],c['value']) for c in direct['checks']}
    missing=ctx['request']|{'height_value':None};probe=ModelTaskRequest.model_validate(missing)
    result={'kind':'same_original_fixed_pipeline_and_agent','origin':'test_fixture_confirmations_real_cpu_tools',
        'backend':ctx['backend'],'source_run_id':run,'fixed_run_id':target,'source_sha256':original_sha,
        'model_revision':rawdata['execution']['upstream_revision'],'input_sha256':rawdata['execution']['input_sha256'],
        'new_model_calls':0,'new_llm_calls':0,'raw_topology':old,'fixed_tool_timings_s':timings,'fixed_postprocess_seconds':time.perf_counter()-start,
        'fixed_inspection':direct,'agent_inspection':actual,'checks_equal':a==b,
        'dimensions_equal':all(abs(x-y)<1e-5 for x,y in zip(actual['dimensions_mm'],direct['dimensions_mm'])),
        'fixed_missing_scale_probe':{'pending_inputs':list(probe.pending_inputs),'behavior':'明确拒绝进入后处理，不提供交互恢复'},
        'agent_resources':{'tool_calls':ctx['tool_calls'],'llm':ctx['llm'],'reconstruction_calls':len(generated)},
        'source_unchanged':original_sha==digest(source_path),'results':results,
        'mesh_error':None,'input_view_iou':None,
        'interpretation':'同一原始网格的固定后处理与Agent采用同一工具和约束；不期待Agent改变几何质量。只比较交互/恢复/停止与调用量，不把分段工具计时和含交互HTTP墙钟直接相减。'}
    result['passed']=result['checks_equal'] and result['dimensions_equal'] and result['source_unchanged']
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--settings',type=Path,required=True);p.add_argument('--run-id',required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.exit(1,'拒绝覆盖已有对照结果\n')
    settings=Settings.model_validate_json(args.settings.read_text(encoding='utf-8'))
    result=compare(settings,args.run_id);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['passed','backend','new_model_calls','new_llm_calls','checks_equal','dimensions_equal','source_unchanged','fixed_postprocess_seconds']},ensure_ascii=False))
    raise SystemExit(not result['passed'])
