"""报告来自任务证据，不让语言模型判定打印通过。"""
import json
from pathlib import Path
from uuid import uuid4
from ..tools import ToolSession
from ..schemas.task import ModelTaskRequest


def write_quality(store, ctx):
    session = ToolSession(store.root, ctx['run_id'], 'export', ctx.get('mesh_version'))
    req = ModelTaskRequest.model_validate(ctx['request'])
    report = {
        'schema_version': 'runtime-v1', 'run_id': ctx['run_id'], 'status': ctx['status'],
        'mesh_version': ctx.get('mesh_version'), 'evidence_origin': ctx.get('evidence_origin', 'runtime'),
        'scale': {'source': req.scale_source, 'evidence_id': req.scale_evidence_id,
            'height_mm': req.height_mm, 'orientation': req.orientation.model_dump(mode='json')},
        'printer_profile': ctx['profile'], 'repair_round': ctx['repair_round'],
        'operations': ctx['operations'], 'inspection': ctx.get('inspection'),
        'inspection_history': ctx.get('inspection_history', []), 'export_readback': ctx.get('export_data'),
        'pending': ctx.get('pending'), 'slicer_confirmation': ctx.get('slicer_confirmation'),
        'human_reviews': ctx.get('human_reviews', []), 'llm': ctx['llm'],
        'delivery_target':'glb' if ctx.get('workflow_policy')=='automatic_glb' else 'print_ready_stl',
        'delivery':ctx.get('delivery'),'delivery_policy':ctx.get('delivery_policy'),'orientation_source':ctx.get('orientation_source'),
        'repair_attempt_log':ctx.get('repair_attempt_log',[]),'automation_origin':'automatic_policy' if ctx.get('workflow_policy')=='automatic_glb' else None,
        'mesh_budget':ctx.get('mesh_budget'),
        'export_options':ctx.get('export_options'),
        'appearance':(ctx.get('export_data') or {}).get('appearance'),
        'gpu_boundary_repair':ctx.get('gpu_boundary_repair'),
        'eye_texture':ctx.get('eye_texture'),
        'active_seconds': (None if ctx.get('interrupted_active_seconds_unknown') else
            store.row(ctx['run_id'])['active_seconds'] + ctx.get('current_active_seconds', 0)),
        'known_completed_active_seconds': store.row(ctx['run_id'])['active_seconds'],
        'resources_note': '等待时间不计活动预算；显存仅引用各工具实际采集值，未采集不填0',
        'unresolved': [c for c in (ctx.get('inspection') or {}).get('checks', []) if c['status'] != 'pass'],
        'error': ctx.get('error'), 'warnings': ctx.get('warnings', []),
        'explanation': ctx.get('explanation'),
        'artifacts': ctx['artifacts'], 'evidence': ctx['evidence']}
    path = session.directory / 'quality.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    md = [f"# 质量报告\n\n任务：{ctx['run_id']}\n\n状态：{ctx['status']}\n\n网格：{ctx.get('mesh_version') or '尚未生成'}",
        f"尺度来源：{req.scale_source or '未知'}；目标高度：{req.height_mm if req.height_mm is not None else '未知'}毫米。",
        f"修复轮数：{ctx['repair_round']}。语言模型调用：{ctx['llm']['calls']}；费用：{ctx['llm']['cost'] if ctx['llm']['cost'] is not None else '未知'}。"]
    if ctx.get('inspection'):
        md.append('| 检查 | 结果 | 数值 |\n| --- | --- | --- |\n' + '\n'.join(
            f"| {c['name']} | {c['status']} | {json.dumps(c['value'], ensure_ascii=False)} |" for c in ctx['inspection']['checks']))
    if ctx.get('workflow_policy')=='automatic_glb':
        delivery=ctx.get('delivery')
        md.append(('GLB生成完成' if ctx['status']=='succeeded' and delivery else 'GLB生成未完成')+'；不代表实际打印合格。')
        md.append(f"检查副本的打印检查：{delivery.get('inspection_print_check',delivery['print_check']) if delivery else 'not_run'}；自动修复尝试：{ctx.get('repair_attempts',0)}轮。自动来源：automatic_policy；没有实际切片/打印确认。")
        if ctx.get('mesh_budget'):
            b=ctx['mesh_budget'];target=b.get('effective_target_faces',b['target_faces'])
            origin='手动' if b.get('selection_source')=='manual' else '自动'
            md.append(f"{origin}面数：图像复杂度{b['classification']}，目标≤{target}面，实际{b.get('actual_faces','未生成')}面。"+(b.get('fallback_reason') or '保形验证及实际检查记录见JSON。'))
        if ctx.get('export_options'):
            requested=ctx['export_options'].get('texture_size')
            md.append(f"请求纹理：{requested or 2048}×{requested or 2048}；实际PBR与纹理状态另见外观记录，TripoSR不使用纹理分辨率。")
    if ctx.get('delivery_policy')=='original-glb-v1':
        md.append('网页交付原始GLB，原UV/贴图/坐标/文件字节保持；未应用目标毫米尺寸或副本修复，原件打印检查为not_run。副本检查不能作为原件认证。')
    if ctx.get('gpu_boundary_repair'):
        gpu=ctx['gpu_boundary_repair']
        md.append(f"首次PBR导出前GPU补片：{gpu['status']}，边界{gpu['boundary_before']}→{gpu['boundary_after']}，实际{gpu['attempts']}轮。"+gpu['warning'])
    if ctx.get('eye_texture'):
        eye=ctx['eye_texture'];scope='眼部及有原图依据的可见皮肤/服装底色、可见头发参考色，背面和遮挡处未恢复' if eye.get('policy_version')=='eye-local-v2' else '眼部底色'
        md.append(f"历史局部底色记录：{eye['status']}；{eye['reason']}。范围：{scope}。此试用现已回退，当前交付使用原始GLB；旧增强件保留，不改变打印结论。")
    if ctx.get('error'): md.append('停止原因：' + ctx['error']['message'])
    appearance=(ctx.get('export_data') or {}).get('appearance')
    if appearance:md.append('外观：'+('原始PBR，未经重烘焙' if appearance['status']=='original_pbr' else '原始顶点色，未经重烘焙' if appearance['status']=='original_vertex_color' else 'PBR纹理已重烘焙至本次处理网格' if appearance['status']=='pbr_rebaked' else '顶点底色')+'；'+(appearance.get('warning') or appearance.get('reason') or '原始PBR来源与重投射参数见JSON。'))
    if ctx.get('explanation'): md.append('语言模型说明（不替代检查证据）：\n\n' + ctx['explanation'])
    md.append('结构化尺度、修改参数、逐版检查、产物与证据、资源及切片记录见同目录quality.json。')
    readable = session.directory / 'quality.md'
    readable.write_text('\n\n'.join(md) + '\n', encoding='utf-8')
    for label, file in [('json', path), ('markdown', readable)]:
        artifact = session.add(label, file, 'quality_report')
        ctx['artifacts'].append(artifact.model_dump(mode='json'))
    ctx['latest_report_ids'] = [a.artifact_id for a in session.artifacts]
    return report
