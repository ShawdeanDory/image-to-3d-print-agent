"""工具节点与interrupt节点分离；同一thread_id始终对应同一run_id。"""
import copy
import json
import time
from typing import TypedDict
from uuid import uuid4
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from ..geometry.commands import dispatch
from ..geometry.core import MeshStore, load_mesh, topology
from ..schemas.task import ModelTaskRequest
from ..schemas.common import MeshInspection, SlicerConfirmation, EvidenceRecord
from ..tools import ToolOutcome, ToolFailure, ToolSession
from ..image.assets import AutomaticInputAcceptance
from ..reports.quality import write_quality
from .llm import LanguageModel
from .state import save_context, fail, response_for


class GraphState(TypedDict):
    ctx: dict
    next: str


QUESTIONS = {'height': '目标高度是多少？', 'height_unit': '高度单位是毫米(mm)还是厘米(cm)？',
    'scale_source': '这是设计目标高度，还是有测量依据的实物高度？', 'orientation': '哪个轴朝上？请确认模型方向。'}


def build_graph(settings, store, checkpointer, tool_dispatch=dispatch, language_model=None):
    llm = language_model or LanguageModel(settings.llm)
    root = store.root
    started = time.perf_counter()

    def persist(ctx, kind='progress', data=None):
        save_context(store, ctx, kind, data)

    def wait_for(ctx, kind, public_type, questions, details=None):
        ctx['pending'] = {'pending_input_id': 'i_' + uuid4().hex, 'kind': kind, 'public_type': public_type,
            'mesh_version': ctx['mesh_version'], 'questions': questions, 'details': details or {}}
        ctx['status'] = 'waiting_for_input'
        ctx['messages'].extend(questions)
        if kind == 'slicer':
            ctx['current_active_seconds'] = time.perf_counter() - started
            write_quality(store, ctx)
        persist(ctx, 'waiting', {'pending': ctx['pending']})
        return 'wait'

    def route(state):
        ctx = copy.deepcopy(state['ctx'])
        if ctx['llm']['availability'] == 'not_checked':
            ctx['llm']['availability'] = 'configured_unused' if settings.llm.configured else 'not_configured'
        if ctx['status'] in {'failed', 'cancelled', 'succeeded'}:
            return {'ctx': ctx, 'next': 'finish'}
        if store.row(ctx['run_id'])['status'] == 'cancel_requested':
            ctx.update(status='cancelled', pending=None, error=None)
            return {'ctx': ctx, 'next': 'finish'}
        ctx['status'] = 'running'
        step = ctx['step']
        nxt = 'finish'
        if step == 'start':
            if not ctx.get('parsed') and ctx['request']['description']: nxt = 'parse'
            else:
                req = ModelTaskRequest.model_validate(ctx['request'])
                if req.pending_inputs or ctx.get('suggestions_unconfirmed'):
                    questions = [QUESTIONS[name] for name in req.pending_inputs]
                    if ctx.get('suggestions_unconfirmed'): questions.append('请核对语言模型提取的约束；姿态必须另行明确确认。')
                    questions.extend((ctx.get('suggestions') or {}).get('questions', []))
                    nxt = wait_for(ctx, 'constraints', req.pending_inputs[0] if req.pending_inputs else 'orientation', questions,
                        {'missing': list(req.pending_inputs), 'suggestions': ctx.get('suggestions')})
                else: nxt = 'prepare'
        elif step == 'prepared':
            ctx['stage'] = 'preprocess'
            if settings.input_review_policy == 'automatic': nxt = 'accept_input'
            else: nxt = wait_for(ctx, 'input_review', 'replacement_image', ['请复核前景、主体完整性及简单非功能摆件适用性。'],
                {'foreground_artifact_id': ctx['prepared']['tool']['data']['foreground_artifact_id'],
                 'mask_artifact_id': ctx['prepared']['tool']['data']['mask_artifact_id']})
        elif step == 'input_received': nxt = 'consume'
        elif step == 'reviewed': nxt = 'reconstruct'
        elif step == 'reconstructed': nxt = 'clean'
        elif step == 'cleaned': nxt = 'scale'
        elif step in {'scaled', 'applied'}: nxt = 'preview'
        elif step == 'oversized':
            ctx['stage'] = 'repair'
            if ctx['repair_round'] >= 2: fail(ctx, 'REPAIR_LIMIT_REACHED', '大网格仍超过处理范围且已达2轮修复上限')
            else:
                nxt = wait_for(ctx, 'repair_request', 'repair_confirmation', ['网格超过50万面，请指定简化目标并预览提案，或停止。'],
                    {'allowed_operations': ['simplify'], 'face_count': ctx['face_count'], 'original_preserved': True})
        elif step == 'previewed':
            nxt = wait_for(ctx, 'print_review', 'orientation', ['请复核本版本预览中的朝向、底面稳定性及组件。'],
                {'preview_artifact_id': ctx['preview_id'], 'component_count': ctx['component_count']})
        elif step == 'print_reviewed': nxt = 'inspect'
        elif step == 'inspected':
            inspection = MeshInspection.model_validate(ctx['inspection'])
            if settings.llm.configured and ctx.get('explanation_version') != ctx['mesh_version']: nxt = 'explain'
            elif inspection.ready_for_print: nxt = 'export'
            elif ctx['repair_round'] >= 2:
                fail(ctx, 'REPAIR_LIMIT_REACHED', '最多2轮修复后仍未满足打印检查，停止交付')
            else:
                checks = {c.name: c for c in inspection.checks}
                allowed = []
                if checks.get('boundary_edges') and checks['boundary_edges'].value:
                    allowed.append('fill_small_holes')
                if inspection.component_count > 1: allowed.append('remove_components')
                if ctx.get('face_count', 0) > 100000: allowed.append('simplify')
                blocking = [c.name for c in inspection.checks if c.status in {'fail', 'not_run'}]
                if not allowed:
                    fail(ctx, 'MESH_NOT_PRINTABLE', '检查未通过且无受支持的自动修复分支', checks=blocking)
                else:
                    ctx['stage'] = 'repair'
                    nxt = wait_for(ctx, 'repair_request', 'repair_confirmation', ['检查未通过，请指定受支持的修复参数，或停止任务。'],
                        {'allowed_operations': allowed, 'blocking_checks': blocking})
        elif step == 'repair_requested': nxt = 'propose'
        elif step == 'proposed':
            nxt = wait_for(ctx, 'repair_confirmation', 'repair_confirmation', ['请预览具体结构提案，确认后才会应用到新版本。'],
                {'proposal_id': ctx['proposal']['proposal_id'], 'source_version': ctx['mesh_version'],
                 'preview_artifact_ids': ctx['proposal_artifact_ids'], 'changes': ctx['proposal']['changes']})
        elif step == 'repair_accepted': nxt = 'confirm'
        elif step == 'confirmed': nxt = 'apply'
        elif step == 'exported':
            ctx['stage'] = 'slicer'
            nxt = wait_for(ctx, 'slicer', 'slicer_confirmation', ['请下载本版本STL并实际切片，上传分层图片并确认尺寸、底面和支撑。'],
                {'export_readback': ctx['export_data'], 'preview_artifact_id': ctx['preview_id']})
        elif step == 'sliced':
            # 公共成功校验是最终门槛；无法通过时不能直接写succeeded。
            ctx.update(stage='complete', pending=None, completion_ready=True)
            response_for({**ctx, 'status': 'succeeded'})
        elif step == 'stopped': pass
        return {'ctx': ctx, 'next': nxt}

    def waiting(state):
        # 本节点没有文件、模型或数据库写入；恢复重放只取人工输入。
        answer = interrupt(state['ctx']['pending'])
        ctx = copy.deepcopy(state['ctx'])
        ctx.update(answer=answer, step='input_received', status='running')
        return {'ctx': ctx}

    def human_record(ctx, answer, kind):
        session = ToolSession(root, ctx['run_id'], 'slice' if kind == 'slicer' else 'preprocess', ctx['mesh_version'])
        path = session.directory / 'human.json'
        origin = settings.confirmation_origin
        payload = {**answer, 'run_id': ctx['run_id'], 'reviewer': settings.operator_name, 'origin': origin}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        artifact = session.add('human', path, 'slicer_confirmation' if kind == 'slicer' else 'inspection_report')
        ctx['artifacts'].append(artifact.model_dump(mode='json'))
        ctx['evidence'].append(EvidenceRecord(evidence_id=session.prefix + '_human', source_type='human' if origin == 'human' else 'tool',
            source_id=answer['submission_id'], run_id=ctx['run_id'], mesh_version=ctx['mesh_version'],
            artifact_id=artifact.artifact_id, locator='human.json', created_at=session.now,
            summary='本任务当前等待项的实际人工提交' if origin == 'human' else '固定样例自动提交，不作实际人工证据').model_dump(mode='json'))
        ctx.setdefault('human_reviews', []).append(payload)
        return artifact.artifact_id

    def accept_input(ctx):
        if settings.input_review_policy != 'automatic':
            raise ToolFailure('STATE_CONFLICT','服务端未启用图片自动继续')
        ctx['pending']=None
        backend_config=settings.tools.backends.get(ctx['backend'])
        if backend_config and backend_config.inference_profile=='official' and ctx['prepared']['tool']['data'].get('method')!='backend_official_preprocessing':
            # 旧检查点不能把历史256像素前景冒充原图；先重新登记同资产原字节。
            outcome=tool(ctx,'prepare_image',asset_id=ctx['request']['image_asset_id'],preprocessing='official_input')
            ctx['prepared']=outcome.model_dump(mode='json')
            report=next(a for a in outcome.artifacts if a.artifact_id.endswith('_report'))
            ctx['prepared_outcome']=str((root/report.relative_path).parent.relative_to(root)/'outcome.json').replace('\\','/')
        review = AutomaticInputAcceptance(asset_id=ctx['request']['image_asset_id'],
            foreground_artifact_id=ctx['prepared']['tool']['data']['foreground_artifact_id'])
        session = ToolSession(root,ctx['run_id'],'preprocess')
        path = session.directory/'automatic-input.json'
        path.write_text(review.model_dump_json(indent=2)+'\n',encoding='utf-8')
        artifact = session.add('automatic_input',path,'inspection_report')
        ctx['artifacts'].append(artifact.model_dump(mode='json'))
        ctx['evidence'].append(EvidenceRecord(evidence_id=session.prefix+'_automatic',source_type='tool',
            source_id=review.asset_id,run_id=ctx['run_id'],artifact_id=artifact.artifact_id,
            locator='automatic-input.json',created_at=session.now,
            summary='服务端图片自动继续政策；未做人工前景或语义复核').model_dump(mode='json'))
        ctx['input_review']=review.model_dump(mode='json')
        ctx['pending']=None
        ctx['step']='reviewed'
        ctx['warnings'].append('图片已自动继续；主体完整性和语义适用性未人工复核。')

    def consume(ctx):
        # 分层图片是在等待期间由API添加；从任务库合并，不能丢失到旧检查点中。
        latest = store.row(ctx['run_id'])['context']
        existing = {a['artifact_id'] for a in ctx['artifacts']}
        ctx['artifacts'].extend(a for a in latest['artifacts'] if a['artifact_id'] not in existing)
        answer = ctx.pop('answer')
        kind = answer['kind']
        if kind == 'automatic_input':
            if not ctx.get('pending') or ctx['pending']['kind']!='input_review' or answer['pending_input_id']!=ctx['pending']['pending_input_id']:
                raise ToolFailure('STATE_CONFLICT','自动接续仅适用于同一图片等待项')
            accept_input(ctx)
            return
        aid = human_record(ctx, answer, kind)
        ctx['pending'] = None
        if kind == 'constraints':
            ctx['request'] = answer['validated_request']
            ctx['suggestions_unconfirmed'] = False
            if ctx['request']['scale_source'] == 'measured_object':
                from ..jobs.service import TaskService
                TaskService(settings).measurement(ctx, ctx['request']['scale_evidence_id'])
            ctx['step'] = 'start'
        elif kind == 'input_review':
            if answer['decision'] != 'accepted' or not all(answer[k] for k in ['complete_subject', 'simple_nonfunctional_ornament', 'foreground_correct']):
                fail(ctx, 'INVALID_IMAGE', '输入未获适用性确认；更换图片须创建新任务')
            else:
                ctx['input_review'] = {k: answer[k] for k in ['foreground_artifact_id', 'decision', 'complete_subject', 'simple_nonfunctional_ornament', 'foreground_correct']}
                ctx['input_review'].update(asset_id=ctx['request']['image_asset_id'], reviewer=settings.operator_name, origin=settings.confirmation_origin)
                ctx['step'] = 'reviewed'
        elif kind == 'print_review':
            if not answer['bed_confirmed']:
                fail(ctx, 'MESH_NOT_PRINTABLE', '人工未确认底面稳定，停止打印交付')
            else:
                ctx['print_review'] = answer
                ctx['step'] = 'print_reviewed'
        elif kind == 'repair_request':
            if answer['stop']: fail(ctx, 'MESH_NOT_PRINTABLE', '用户选择停止修复')
            else:
                ctx['structure_request'] = answer['request']
                ctx['step'] = 'repair_requested'
        elif kind == 'repair_confirmation':
            if not answer['accepted']: fail(ctx, 'MESH_NOT_PRINTABLE', '用户拒绝当前结构修改，未应用提案')
            else: ctx['step'] = 'repair_accepted'
        else:
            confirmation = SlicerConfirmation.model_validate({k: answer[k] for k in [
                'pending_input_id', 'mesh_version', 'result', 'slicer_version', 'printer_profile_id',
                'dimensions_mm', 'supports_enabled', 'layer_preview_asset_id', 'notes'] } | {'confirmation_artifact_id': aid})
            ctx['slicer_confirmation'] = confirmation.model_dump(mode='json')
            if answer['result'] == 'fail': fail(ctx, 'SLICER_VALIDATION_FAILED', '用户实际切片复核失败')
            else: ctx['step'] = 'sliced'

    def tool(ctx, operation, **arguments):
        if ctx['tool_calls'] >= settings.max_tool_calls:
            raise ToolFailure('BUDGET_NOT_CONFIGURED', '工具调用上限已达，不再继续执行')
        ctx['tool_calls'] += 1
        ctx['inflight'] = operation
        persist(ctx, 'tool_started', {'operation': operation, 'call': ctx['tool_calls']})
        outcome = ToolOutcome.model_validate(tool_dispatch(root, {'run_id': ctx['run_id'], 'operation': operation, **arguments},
            settings.tools, human_action=True, confirmation_origin=settings.confirmation_origin,
            automatic_input=settings.input_review_policy=='automatic'))
        if str(outcome.tool.run_id) != ctx['run_id'] or any(str(a.run_id) != ctx['run_id'] for a in outcome.artifacts):
            raise ToolFailure('STATE_CONFLICT', '工具返回了其他任务的产物')
        known_artifacts = {a['artifact_id'] for a in ctx['artifacts']} | {a.artifact_id for a in outcome.artifacts}
        known_evidence = {e['evidence_id'] for e in ctx['evidence']} | {e.evidence_id for e in outcome.evidence}
        if not set(outcome.tool.artifact_ids) <= known_artifacts or not set(outcome.tool.evidence_ids) <= known_evidence:
            raise ToolFailure('STATE_CONFLICT', '工具引用了未登记的产物或证据')
        ctx['artifacts'].extend(a.model_dump(mode='json') for a in outcome.artifacts)
        ctx['evidence'].extend(e.model_dump(mode='json') for e in outcome.evidence)
        frames=outcome.tool.data.get('artifact_frames',{})
        if not isinstance(frames,dict) or not set(frames)<=known_artifacts or any(v not in {'y_up','z_up'} for v in frames.values()):
            raise ToolFailure('STATE_CONFLICT','产物显示坐标引用无效')
        ctx.setdefault('artifact_frames',{}).update(frames)
        ctx['operations'].append({'operation': operation, 'mesh_version': ctx['mesh_version'],
            'result': outcome.tool.model_dump(mode='json')})
        ctx.pop('inflight', None)
        data = outcome.tool.data
        if operation == 'inspect' and data.get('inspection'):
            if data['inspection']['mesh_version'] != ctx['mesh_version']:
                raise ToolFailure('STATE_CONFLICT', '检查结果对应其他网格版本')
            ctx['inspection'] = data['inspection']
            ctx.setdefault('inspection_history', []).append(data['inspection'])
        if not outcome.tool.succeeded:
            raise ToolFailure(outcome.tool.error.code, outcome.tool.error.message)
        if operation in {'preview', 'export'} and data.get('mesh_version') != ctx['mesh_version']:
            raise ToolFailure('STATE_CONFLICT', '工具预览/导出版本与当前网格不匹配')
        if operation in {'reconstruct', 'clean', 'scale', 'apply'}:
            ctx['mesh_version'] = data['mesh_version']
            source = MeshStore(root).get(ctx['run_id'], ctx['mesh_version'])
            ctx['repair_round'] = source.repair_round
            ctx['inspection'] = None
            ctx['explanation'] = None
        return outcome

    def execute(name):
        def node(state):
            ctx = copy.deepcopy(state['ctx'])
            try:
                ctx['status'] = 'running'
                if name == 'consume': consume(ctx)
                elif name == 'accept_input': accept_input(ctx)
                elif name == 'parse':
                    ctx['stage'] = 'input'
                    parsed = llm.call(ctx, store, 'parse', {'description': ctx['request']['description'],
                        'structured_request': ctx['request']})
                    ctx.update(parsed=True, suggestions=parsed.model_dump(mode='json'), suggestions_unconfirmed=True, step='start')
                elif name == 'explain':
                    ctx['explanation_version'] = ctx['mesh_version']
                    inspection = ctx.get('inspection')
                    summary = {'mesh_version': ctx['mesh_version'], 'dimensions_mm': inspection['dimensions_mm'],
                        'checks': [{k: c[k] for k in ['name', 'status', 'value', 'threshold']} for c in inspection['checks']]} if inspection else None
                    ctx['explanation'] = llm.call(ctx, store, 'explain', {'inspection': summary,
                        'error': ctx.get('error'), 'export': ctx.get('export_data')}).explanation
                elif name == 'prepare':
                    ctx['stage'] = 'preprocess'
                    backend_config=settings.tools.backends.get(ctx['backend'])
                    preparation='official_input' if backend_config and backend_config.inference_profile=='official' else 'legacy_foreground'
                    outcome = tool(ctx, 'prepare_image', asset_id=ctx['request']['image_asset_id'], background_backend=settings.background_backend,
                        preprocessing=preparation)
                    ctx['prepared'] = outcome.model_dump(mode='json')
                    report = next(a for a in outcome.artifacts if a.artifact_id.endswith('_report'))
                    ctx['prepared_outcome'] = str((root / report.relative_path).parent.relative_to(root) / 'outcome.json').replace('\\', '/')
                    ctx['step'] = 'prepared'
                elif name == 'reconstruct':
                    ctx['stage'] = 'reconstruct'
                    if ctx['backend'] is None: raise ToolFailure('MODEL_NOT_CONFIGURED', '未显式选择重建后端')
                    extra={'reconstruction_profile':ctx['reconstruction_profile']} if ctx.get('reconstruction_profile') else {}
                    outcome=tool(ctx, name, backend=ctx['backend'], prepared_outcome=ctx['prepared_outcome'], review=ctx['input_review'],**extra)
                    ctx['reconstruction_metrics']=outcome.tool.data.get('model')
                    ctx['step'] = 'reconstructed'
                elif name == 'clean':
                    ctx['stage'] = 'repair'
                    tool(ctx, name, mesh_version=ctx['mesh_version'])
                    ctx['step'] = 'cleaned'
                elif name == 'scale':
                    ctx['stage'] = 'scale'
                    tool(ctx, name, mesh_version=ctx['mesh_version'], request=ctx['request'])
                    ctx['step'] = 'scaled'
                elif name == 'preview':
                    source = MeshStore(root).get(ctx['run_id'], ctx['mesh_version'])
                    facts = topology(load_mesh(root / source.relative_path))
                    ctx.update(component_count=facts['component_count'], face_count=facts['face_count'])
                    if facts['face_count'] > 500000: ctx['step'] = 'oversized'
                    else:
                        outcome = tool(ctx, name, mesh_version=ctx['mesh_version'])
                        preview = next(a for a in outcome.artifacts if a.relative_path.endswith('preview.png'))
                        ctx['preview_id'] = preview.artifact_id
                        ctx['step'] = 'previewed'
                elif name == 'inspect':
                    ctx['stage'] = 'inspect'
                    review = ctx['print_review']
                    bed = {'mesh_version': ctx['mesh_version'], 'confirmed': review['bed_confirmed'], 'reviewer': settings.operator_name, 'origin':settings.confirmation_origin}
                    component = None
                    if review['components_confirmed']:
                        component = {'mesh_version': ctx['mesh_version'], 'component_count': review['component_count'],
                            'confirmed': True, 'reviewer': settings.operator_name, 'origin':settings.confirmation_origin}
                    tool(ctx, name, mesh_version=ctx['mesh_version'], profile=ctx['profile'],
                        height_mm=ModelTaskRequest.model_validate(ctx['request']).height_mm, bed_review=bed, component_review=component)
                    ctx['step'] = 'inspected'
                elif name == 'propose':
                    ctx['stage'] = 'repair'
                    if ctx['repair_round'] >= 2: raise ToolFailure('REPAIR_LIMIT_REACHED', '已达2轮修复上限')
                    outcome = tool(ctx, name, mesh_version=ctx['mesh_version'], request=ctx['structure_request'])
                    ctx.update(proposal=outcome.tool.data['proposal'], proposal_artifact_ids=[a.artifact_id for a in outcome.artifacts], step='proposed')
                elif name == 'confirm':
                    if ctx['proposal']['source_version'] != ctx['mesh_version']: raise ToolFailure('STATE_CONFLICT', '提案源版本已过期')
                    tool(ctx, name, proposal_id=ctx['proposal']['proposal_id'], reviewer=settings.operator_name, accepted=True)
                    ctx['step'] = 'confirmed'
                elif name == 'apply':
                    tool(ctx, name, proposal_id=ctx['proposal']['proposal_id'])
                    ctx['step'] = 'applied'
                elif name == 'export':
                    ctx['stage'] = 'export'
                    outcome = tool(ctx, name, mesh_version=ctx['mesh_version'])
                    if not outcome.tool.data.get('independent_readback'):
                        raise ToolFailure('STATE_CONFLICT', '导出缺少独立重读证据')
                    ctx.update(export_data=outcome.tool.data, step='exported')
                persist(ctx, 'node_completed', {'node': name})
            except ToolFailure as exc:
                if name == 'explain':
                    ctx.setdefault('warnings', []).append('语言模型说明不可用：' + str(exc))
                    ctx['llm_explanation_error'] = {'code': exc.code, 'message': str(exc)}
                else: fail(ctx, exc.code, str(exc))
                persist(ctx, 'node_failed', {'node': name})
            except (ValueError, OSError, KeyError, StopIteration):
                fail(ctx, 'TOOL_UNAVAILABLE', '节点返回或文件证据无效，已停止；详见服务端错误记录', node=name)
                persist(ctx, 'node_failed', {'node': name})
            return {'ctx': ctx}
        return node

    def finish(state):
        ctx = copy.deepcopy(state['ctx'])
        if ctx.get('completion_ready') and ctx['status'] == 'running': ctx['status'] = 'succeeded'
        if ctx['llm']['availability'] == 'not_checked':
            ctx['llm']['availability'] = 'configured_unused' if settings.llm.configured else 'not_configured'
        ctx['current_active_seconds'] = time.perf_counter() - started
        write_quality(store, ctx)
        persist(ctx, 'completed')
        return {'ctx': ctx}

    builder = StateGraph(GraphState)
    builder.add_node('route', route)
    builder.add_node('wait', waiting)
    builder.add_node('finish', finish)
    nodes = ['consume', 'accept_input', 'parse', 'explain', 'prepare', 'reconstruct', 'clean', 'scale', 'preview', 'inspect', 'propose', 'confirm', 'apply', 'export']
    for name in nodes:
        builder.add_node(name, execute(name))
        builder.add_edge(name, 'route')
    builder.add_edge(START, 'route')
    builder.add_conditional_edges('route', lambda state: state['next'], {n: n for n in [*nodes, 'wait', 'finish']})
    builder.add_edge('wait', 'route')
    builder.add_edge('finish', END)
    return builder.compile(checkpointer=checkpointer)
