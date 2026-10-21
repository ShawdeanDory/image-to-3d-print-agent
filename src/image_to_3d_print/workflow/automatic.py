"""一次提交的GLB生成图；自动策略、检查结论和实际打印认证分别记录。"""
import copy
import time
from langgraph.graph import StateGraph,START,END
from ..geometry.commands import dispatch
from ..geometry.core import MeshStore,load_mesh,topology
from ..image.assets import AutomaticInputAcceptance
from ..schemas.task import ModelTaskRequest
from ..schemas.common import MeshInspection
from ..tools import ToolFailure,ToolOutcome
from ..runtime_contracts import GenerationDelivery,print_check_for
from ..reports.quality import write_quality
from .state import save_context,fail
from .llm import LanguageModel


def build_generation_graph(settings,store,checkpointer,tool_dispatch=dispatch,language_model=None):
    root=store.root;started=time.perf_counter();llm=language_model or LanguageModel(settings.llm)

    def persist(ctx,kind='progress',data=None):save_context(store,ctx,kind,data)

    def tool(ctx,operation,**arguments):
        if store.row(ctx['run_id'])['status']=='cancel_requested':raise ToolFailure('STATE_CONFLICT','任务已请求取消')
        if ctx['tool_calls']>=settings.max_tool_calls:raise ToolFailure('BUDGET_NOT_CONFIGURED','工具调用上限已达')
        ctx['tool_calls']+=1;ctx['inflight']=operation
        persist(ctx,'tool_started',{'operation':operation,'origin':'automatic_policy'})
        outcome=ToolOutcome.model_validate(tool_dispatch(root,{'run_id':ctx['run_id'],'operation':operation,**arguments},settings.tools,
            human_action=False,confirmation_origin='automatic_policy',automatic_action=True,automatic_input=True))
        if str(outcome.tool.run_id)!=ctx['run_id'] or any(str(a.run_id)!=ctx['run_id'] for a in outcome.artifacts):
            raise ToolFailure('STATE_CONFLICT','工具返回了其他任务产物')
        ids={a['artifact_id'] for a in ctx['artifacts']}|{a.artifact_id for a in outcome.artifacts}
        evidence={e['evidence_id'] for e in ctx['evidence']}|{e.evidence_id for e in outcome.evidence}
        if not set(outcome.tool.artifact_ids)<=ids or not set(outcome.tool.evidence_ids)<=evidence:
            raise ToolFailure('STATE_CONFLICT','工具证据引用无效')
        frames=outcome.tool.data.get('artifact_frames',{})
        if not set(frames)<=ids or any(f not in {'z_up','y_up'} for f in frames.values()):raise ToolFailure('STATE_CONFLICT','显示坐标无效')
        ctx['artifacts'].extend(a.model_dump(mode='json') for a in outcome.artifacts)
        ctx['evidence'].extend(e.model_dump(mode='json') for e in outcome.evidence)
        ctx.setdefault('artifact_frames',{}).update(frames)
        ctx['operations'].append({'operation':operation,'mesh_version':ctx.get('mesh_version'),'origin':'automatic_policy','result':outcome.tool.model_dump(mode='json')})
        ctx.pop('inflight',None)
        if outcome.tool.succeeded and operation in {'reconstruct','clean','scale','apply'}:
            version=outcome.tool.data['mesh_version'];source=MeshStore(root).get(ctx['run_id'],version)
            ctx.update(mesh_version=version,repair_round=source.repair_round,inspection=None)
        if not outcome.tool.succeeded:raise ToolFailure(outcome.tool.error.code,outcome.tool.error.message)
        return outcome

    def choose_repair(ctx):
        source=MeshStore(root).get(ctx['run_id'],ctx['mesh_version']);mesh=load_mesh(root/source.relative_path);facts=topology(mesh)
        tried={(x['mesh_version'],x['operation']) for x in ctx.get('repair_attempt_log',[])}
        options=[]
        if facts['boundary_edge_count']:options.append({'operation':'fill_small_holes','max_perimeter_mm':40.})
        if facts['component_count']>1 and not facts['non_manifold_edge_count'] and not facts['non_manifold_vertex_count']:
            parts=list(mesh.split(only_watertight=False));area=sum(p.area for p in parts)
            small=[i for i,p in enumerate(parts) if p.area<=area*.01 and len(p.faces)<=len(mesh.faces)*.01]
            if small and len(small)<len(parts):options.append({'operation':'remove_components','remove_components':small})
        if facts['face_count']>100000:options.append({'operation':'simplify','target_faces':100000,'min_wall_mm':float(ctx['profile']['min_wall_mm'])})
        return next((o for o in options if (source.mesh_version,o['operation']) not in tried),None)

    def node(name):
        def execute(state):
            ctx=copy.deepcopy(state['ctx']);ctx['next']='finish'
            if ctx['status'] in {'failed','cancelled','succeeded'}:return {'ctx':ctx}
            try:
                if store.row(ctx['run_id'])['status']=='cancel_requested':
                    ctx.update(status='cancelled',pending=None,error=None);return {'ctx':ctx}
                ctx.update(status='running',pending=None)
                if name=='prepare':
                    ctx['stage']='preprocess'
                    outcome=tool(ctx,'prepare_image',asset_id=ctx['request']['image_asset_id'],preprocessing='official_input')
                    report=next(a for a in outcome.artifacts if a.artifact_id.endswith('_report'))
                    ctx['prepared_outcome']=str((root/report.relative_path).parent.relative_to(root)/'outcome.json').replace('\\','/')
                    ctx['prepared']=outcome.tool.data;ctx['next']='reconstruct'
                elif name=='reconstruct':
                    ctx['stage']='reconstruct'
                    review=AutomaticInputAcceptance(asset_id=ctx['request']['image_asset_id'],foreground_artifact_id=ctx['prepared']['foreground_artifact_id'])
                    args={'reconstruction_profile':ctx['reconstruction_profile']} if ctx.get('reconstruction_profile') else {}
                    outcome=tool(ctx,'reconstruct',backend=ctx['backend'],prepared_outcome=ctx['prepared_outcome'],review=review.model_dump(),**args)
                    ctx['reconstruction_metrics']=outcome.tool.data.get('model');ctx['next']='clean'
                elif name=='clean':
                    ctx['stage']='repair';tool(ctx,'clean',mesh_version=ctx['mesh_version']);ctx['next']='scale'
                elif name=='scale':
                    ctx['stage']='scale';tool(ctx,'scale',mesh_version=ctx['mesh_version'],request=ctx['request']);ctx['next']='inspect'
                elif name=='inspect':
                    ctx['stage']='inspect'
                    outcome=tool(ctx,'inspect',mesh_version=ctx['mesh_version'],profile=ctx['profile'],height_mm=ModelTaskRequest.model_validate(ctx['request']).height_mm)
                    inspection=MeshInspection.model_validate(outcome.tool.data['inspection'])
                    if inspection.mesh_version!=ctx['mesh_version']:raise ToolFailure('STATE_CONFLICT','检查版本不匹配')
                    ctx['inspection']=inspection.model_dump(mode='json');ctx.setdefault('inspection_history',[]).append(ctx['inspection'])
                    score=(sum(c.status=='not_run' for c in inspection.checks),sum(c.status=='fail' for c in inspection.checks),inspection.boundary_edge_count+inspection.non_manifold_edge_count+inspection.non_manifold_vertex_count)
                    if not ctx.get('best_checked') or tuple(ctx['best_checked']['score'])>score:
                        ctx['best_checked']={'score':list(score),'mesh_version':ctx['mesh_version'],'inspection':ctx['inspection']}
                    ctx['next']='plan'
                elif name=='plan':
                    inspection=MeshInspection.model_validate(ctx['inspection']) if ctx.get('inspection') else None
                    if inspection is not None and inspection.ready_for_print or ctx.get('repair_attempts',0)>=2:
                        ctx['next']='deliver'
                    else:
                        request=choose_repair(ctx)
                        if request is None:
                            ctx['warnings'].append('没有适用的受控修复操作，保留当前有效网格。');ctx['next']='deliver'
                        else:
                            ctx['repair_attempts']=ctx.get('repair_attempts',0)+1
                            ctx.setdefault('repair_attempt_log',[]).append({'attempt':ctx['repair_attempts'],'mesh_version':ctx['mesh_version'],'operation':request['operation'],'status':'planned','origin':'automatic_policy'})
                            ctx['auto_request']=request;ctx['next']='propose'
                elif name=='propose':
                    ctx['stage']='repair'
                    result=tool(ctx,'propose',mesh_version=ctx['mesh_version'],request=ctx['auto_request'])
                    ctx['proposal']=result.tool.data['proposal'];ctx['next']='confirm'
                elif name=='confirm':
                    ctx['stage']='repair'
                    tool(ctx,'confirm',proposal_id=ctx['proposal']['proposal_id'],reviewer='automatic_policy_v1',accepted=True)
                    ctx['next']='apply'
                elif name=='apply':
                    ctx['stage']='repair';tool(ctx,'apply',proposal_id=ctx['proposal']['proposal_id'])
                    ctx['repair_attempt_log'][-1]['status']='applied';ctx['next']='inspect'
                elif name=='deliver':
                    ctx['stage']='export'
                    best=ctx.get('best_checked')
                    if best:
                        ctx.update(mesh_version=best['mesh_version'],inspection=best['inspection'])
                        ctx['repair_round']=MeshStore(root).get(ctx['run_id'],ctx['mesh_version']).repair_round
                    outcome=tool(ctx,'export_glb',mesh_version=ctx['mesh_version']);data=outcome.tool.data
                    if data.get('mesh_version')!=ctx['mesh_version'] or data.get('independent_readback') is not True:
                        raise ToolFailure('STATE_CONFLICT','GLB缺少本版本独立读回证据')
                    inspection=MeshInspection.model_validate(ctx['inspection']) if ctx.get('inspection') else None
                    status=print_check_for(inspection)
                    if status!='passed':ctx['warnings'].append('GLB已生成；打印检查未通过或未完整执行，不能作为打印合格证明。')
                    ctx['delivery']=GenerationDelivery(artifact_id=data['artifact_id'],mesh_version=ctx['mesh_version'],
                        independent_readback=True,print_check=status,repair_attempts=ctx.get('repair_attempts',0),dimensions_mm=data['dimensions_mm'],warnings=ctx['warnings']).model_dump(mode='json')
                    ctx['export_data']=data;ctx['next']='explain' if settings.llm.configured else 'finish'
                elif name=='explain':
                    inspection=ctx.get('inspection') or {}
                    ctx['explanation']=llm.call(ctx,store,'explain',{'mesh_version':ctx['mesh_version'],
                        'checks':[{k:c[k] for k in ['name','status','value','threshold']} for c in inspection.get('checks',[])],
                        'delivery':ctx['delivery']}).explanation
                persist(ctx,'node_completed',{'node':name,'origin':'automatic_policy'})
            except (ToolFailure,ValueError,OSError,KeyError,StopIteration) as exc:
                code=exc.code if isinstance(exc,ToolFailure) else 'TOOL_UNAVAILABLE'
                if name in {'propose','confirm','apply'} and code not in {'STATE_CONFLICT','BUDGET_NOT_CONFIGURED'}:
                    ctx['repair_attempt_log'][-1].update(status='failed',error={'code':code,'message':str(exc)[:300]})
                    ctx['warnings'].append('受控修复未执行或失败：'+str(exc)[:200]);ctx['next']='plan'
                elif name=='inspect' and code not in {'STATE_CONFLICT','BUDGET_NOT_CONFIGURED'}:
                    partial=ctx['operations'][-1]['result']['data'].get('inspection') if ctx['operations'] else None
                    ctx['inspection']=None
                    if partial and partial.get('mesh_version')==ctx['mesh_version']:
                        ctx['inspection']=MeshInspection.model_validate(partial).model_dump(mode='json')
                        ctx.setdefault('inspection_history',[]).append(ctx['inspection'])
                    ctx['warnings'].append('打印检查未完整执行：'+str(exc)[:200]);ctx['next']='deliver'
                elif name=='explain':ctx['warnings'].append('语言模型说明不可用，保留确定性报告。')
                else:fail(ctx,code,str(exc)[:500]);ctx['next']='finish'
                persist(ctx,'node_failed',{'node':name,'code':code,'origin':'automatic_policy'})
            return {'ctx':ctx}
        return execute

    def finish(state):
        ctx=copy.deepcopy(state['ctx']);ctx['pending']=None
        if store.row(ctx['run_id'])['status']=='cancel_requested':ctx.update(status='cancelled',error=None)
        elif ctx['status']=='running' and ctx.get('delivery'):ctx.update(status='succeeded',stage='complete',error=None)
        elif ctx['status']=='running':fail(ctx,'TOOL_UNAVAILABLE','未取得有效GLB，不能完成生成')
        ctx['llm']['availability']='configured_unused' if settings.llm.configured and not ctx['llm']['calls'] else 'not_configured' if not settings.llm.configured else 'configured_used'
        ctx['current_active_seconds']=time.perf_counter()-started
        write_quality(store,ctx);persist(ctx,'completed',{'target':'glb','origin':'automatic_policy'})
        return {'ctx':ctx}

    builder=StateGraph(dict);nodes=['prepare','reconstruct','clean','scale','inspect','plan','propose','confirm','apply','deliver','explain']
    for name in nodes:
        builder.add_node(name,node(name));builder.add_conditional_edges(name,lambda state:state['ctx']['next'],{n:n for n in [*nodes,'finish']})
    builder.add_node('finish',finish);builder.add_edge(START,'prepare');builder.add_edge('finish',END)
    return builder.compile(checkpointer=checkpointer)
