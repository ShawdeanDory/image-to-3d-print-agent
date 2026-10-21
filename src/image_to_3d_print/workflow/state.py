"""从唯一运行上下文构造公共响应，不另造状态枚举。"""
from uuid import UUID
from ..schemas.task import ModelTaskResponse


def response_for(ctx):
    pending = ctx.get('pending')
    state = {
        'run_id': ctx['run_id'], 'stage': ctx['stage'], 'status': ctx['status'],
        'pending_input_id': pending['pending_input_id'] if pending else None,
        'pending_input_type': pending['public_type'] if pending else None,
        'mesh_version': ctx.get('mesh_version'), 'repair_round': ctx.get('repair_round', 0),
        'artifacts': [a['artifact_id'] for a in ctx['artifacts']],
        'checks': (ctx.get('inspection') or {}).get('checks', []),
        'warnings': ctx.get('warnings', []), 'error': ctx.get('error')}
    result = ModelTaskResponse.model_validate({
        'request_id': ctx['run_id'], 'run_id': ctx['run_id'], 'status': ctx['status'],
        'data': {'request': ctx['request'], 'state': state, 'printer_profile': ctx['profile'],
            'inspection': ctx.get('inspection'), 'slicer_confirmation': ctx.get('slicer_confirmation')},
        'artifacts': ctx['artifacts'], 'evidence': ctx['evidence'],
        'events': ctx.get('messages', []), 'warnings': ctx.get('warnings', []), 'error': ctx.get('error')})
    return result.model_dump(mode='json')


def save_context(store, ctx, kind='progress', data=None):
    store.save(ctx, response_for(ctx), kind, data)


def fail(ctx, code, message, **details):
    ctx.update(status='failed', pending=None, error={'code': code, 'message': message, 'details': details})
    return ctx


def initial_context(run, request, profile, backend):
    return {'run_id': str(UUID(str(run))), 'request': request, 'profile': profile,
        'backend': backend, 'status': 'queued', 'stage': 'input', 'step': 'start',
        'artifacts': [], 'evidence': [], 'messages': [], 'warnings': [], 'operations': [],
        'tool_calls': 0, 'repair_round': 0, 'mesh_version': None, 'pending': None,
        'llm': {'availability': 'not_checked', 'calls': 0, 'input_tokens': 0,
            'output_tokens': 0, 'reserved_tokens': 0, 'usage_complete': True, 'cost': None, 'records': []}}
