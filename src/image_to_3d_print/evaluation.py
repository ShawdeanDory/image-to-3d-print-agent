"""基于实际质量报告的汇总、同任务对照及冻结门禁；不隐式运行模型或保留集。"""
import argparse
import json
from pathlib import Path
from typing import Literal
from pydantic import Field,StrictBool
from .schemas.common import ContractModel,Text

class EvaluationPlan(ContractModel):
    dataset_version:Text
    backend:Literal['triposr','trellis2_candidate']
    model_revision:Text
    code_revision:Text
    protocol_version:Text
    split:Literal['development','evaluation','holdout']='development'

class FreezeApproval(EvaluationPlan):
    split:Literal['holdout']='holdout'
    reviewer:Text
    origin:Literal['human','test_fixture']
    backend_selected:StrictBool
    camera_approved:StrictBool
    successful_print_paths:int=Field(ge=0)
    slicer_objects:int=Field(ge=0)

def gate(plan:EvaluationPlan,approval:FreezeApproval|None):
    """这里只校验执行前置，不以可伪造的布尔值宣称已实际冻结或执行。"""
    if plan.split!='holdout':return {'allowed':True,'reasons':[],'execution':'not_run'}
    reasons=[]
    if approval is None:reasons.append('未提供真实人工冻结记录')
    else:
        if approval.origin!='human':reasons.append('测试记录不能批准真实保留集')
        for key in ['dataset_version','backend','model_revision','code_revision','protocol_version']:
            if getattr(plan,key)!=getattr(approval,key):reasons.append(key+'与冻结记录不一致')
        if not approval.backend_selected:reasons.append('尚未完成主后端选型')
        if not approval.camera_approved:reasons.append('输入视角映射尚未批准')
        if approval.successful_print_paths<3:reasons.append('不足3个真实正常对象完整路径')
        if approval.slicer_objects<1:reasons.append('尚无对应实际切片对象')
    return {'allowed':not reasons,'reasons':reasons,'execution':'not_run'}

def backend(report):
    if report.get('backend'):return report['backend']
    for operation in report.get('operations',[]):
        data=operation.get('result',{}).get('data',{})
        if operation.get('operation')=='reconstruct':
            named=data.get('backend') or data.get('execution',{}).get('backend')
            if named:return named
    raise ValueError('报告缺显式重建后端，不猜测模型来源')

def metrics(inspection):
    if not inspection:return {'mesh_version':None,'dimensions_mm':None,'checks':{},'unexecuted':[]}
    checks=inspection.get('checks',[])
    return {'mesh_version':inspection['mesh_version'],'dimensions_mm':inspection.get('dimensions_mm'),
        'checks':{c['name']:{'status':c['status'],'value':c.get('value'),'unit':c.get('unit')} for c in checks},
        'unexecuted':[c['name'] for c in checks if c['status']=='not_run']}

def compare_reports(before,after):
    if backend(before)!=backend(after):raise ValueError('修复/Agent对照必须固定同一后端')
    if before['run_id']!=after['run_id']:raise ValueError('此入口只比较同一任务、同一原始生成结果的报告，不将独立重建冒充配对')
    def source(report):
        generated=[op.get('result',{}).get('data',{}) for op in report.get('operations',[]) if op.get('operation')=='reconstruct']
        if len(generated)!=1 or not generated[0].get('mesh_version'):raise ValueError('缺唯一原始重建引用，不作配对')
        return generated[0]['mesh_version']
    if source(before)!=source(after):raise ValueError('原始重建引用不一致')
    return {'run_id':before['run_id'],'backend':backend(before),'before':metrics(before.get('inspection')),
        'after':metrics(after.get('inspection')),'active_seconds_before':before.get('active_seconds'),
        'active_seconds_after':after.get('active_seconds'),'mesh_error':None,'input_view_iou':None,
        'note':'无合法参考网格不计算网格误差；输入视角未批准不计算质量IoU。纯工具对照须另存来源。'}

def summarize(reports):
    runs=[r['run_id'] for r in reports]
    if len(set(runs))!=len(runs):raise ValueError('同一任务重复报告不得进入统计分母')
    real=[r for r in reports if r.get('evidence_origin')=='runtime'];fixtures=[r for r in reports if r.get('evidence_origin')=='test_fixture']
    unknown=[r for r in reports if r.get('evidence_origin') not in {'runtime','test_fixture'}]
    costs=[r.get('llm',{}).get('cost') for r in real]
    return {'report_count':len(reports),'real_runs':len(real),'fixture_runs':len(fixtures),'unknown_origin':len(unknown),
        'real_succeeded':sum(r['status']=='succeeded' for r in real),'real_failed':sum(r['status']=='failed' for r in real),
        'cost_total':sum(costs) if costs and all(c is not None for c in costs) else None,
        'final_success_rate':None,'rate_note':'未执行冻结数据集，不外推正式成功率',
        'runs':[{'run_id':r['run_id'],'status':r['status'],'origin':r.get('evidence_origin'),'inspection':metrics(r.get('inspection')),
            'active_seconds':r.get('active_seconds'),'llm':r.get('llm'),'error':r.get('error')} for r in reports]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports',type=Path,nargs='*',default=[])
    parser.add_argument('--plan',type=Path);parser.add_argument('--approval',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result={}
    if args.plan:
        plan=EvaluationPlan.model_validate_json(args.plan.read_text(encoding='utf-8'))
        approval=FreezeApproval.model_validate_json(args.approval.read_text(encoding='utf-8')) if args.approval else None
        result['gate']=gate(plan,approval);result['plan']=plan.model_dump(mode='json')
    if args.reports:result['summary']=summarize([json.loads(f.read_text(encoding='utf-8')) for f in args.reports])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists():parser.exit(1,'拒绝覆盖既有评估记录\n')
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output),'holdout_execution':'not_run','gate':result.get('gate')},ensure_ascii=False))
    return bool(args.plan and not result['gate']['allowed'])

if __name__=='__main__':raise SystemExit(main())
