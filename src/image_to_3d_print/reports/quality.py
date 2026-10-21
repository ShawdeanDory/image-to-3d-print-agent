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
    if ctx.get('error'): md.append('停止原因：' + ctx['error']['message'])
    if ctx.get('explanation'): md.append('语言模型说明（不替代检查证据）：\n\n' + ctx['explanation'])
    md.append('结构化尺度、修改参数、逐版检查、产物与证据、资源及切片记录见同目录quality.json。')
    readable = session.directory / 'quality.md'
    readable.write_text('\n\n'.join(md) + '\n', encoding='utf-8')
    for label, file in [('json', path), ('markdown', readable)]:
        artifact = session.add(label, file, 'quality_report')
        ctx['artifacts'].append(artifact.model_dump(mode='json'))
    ctx['latest_report_ids'] = [a.artifact_id for a in session.artifacts]
    return report
