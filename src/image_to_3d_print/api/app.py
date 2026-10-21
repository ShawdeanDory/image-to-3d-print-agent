"""API只校验、持久化和排队；工具由独立worker执行。"""
import os
import secrets
from typing import Annotated, Literal
from uuid import UUID
from fastapi import FastAPI, UploadFile, File, Header, Query, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from ..jobs.config import Settings
from ..jobs.service import TaskService, INPUTS
from ..runtime_contracts import CreateTask, Submission, RuntimeTask, PendingInput, EventsPage, GenerationTaskResponse
from ..schemas.task import ModelTaskRequest, ModelTaskResponse
from ..schemas.common import Id
from ..schemas.validation import resolve_artifact_path
from ..tools import ToolFailure


def create_app(settings=None):
    settings = settings or Settings.from_env()
    service = TaskService(settings)
    def authorize(authorization: str | None = Header(default=None)):
        expected = os.environ.get(settings.api_token_env)
        if expected and not secrets.compare_digest(authorization or '', 'Bearer ' + expected):
            raise HTTPException(401, '需要本地服务访问凭据')
    app = FastAPI(title='图像到3D打印Agent', version='runtime-v1', dependencies=[Depends(authorize)])
    app.state.service = service
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
            allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type', 'Idempotency-Key'])

    @app.exception_handler(ToolFailure)
    async def tool_error(request: Request, exc: ToolFailure):
        code = {'REFERENCE_NOT_FOUND': 404, 'STATE_CONFLICT': 409}.get(exc.code, 422)
        return JSONResponse(status_code=code, content={'error': {'code': exc.code, 'message': str(exc), 'details': {}}})

    @app.get('/api/v1/configuration')
    def configuration():
        return {'schema_version': 'runtime-v1', 'default_backend': settings.default_backend,
            'configured_backends': list(settings.tools.backends), 'inspection_configured': settings.tools.inspection is not None,
            'llm_configured': settings.llm.configured, 'llm_model': settings.llm.model,
            'confirmation_origin': settings.confirmation_origin,
            'input_review_policy': settings.input_review_policy,
            'workflow_policy':settings.workflow_policy,
            'backend_profiles':{name:['course_fast'] if name=='trellis2_candidate' and settings.workflow_policy=='automatic_glb' else ['official','course_fast'] if name=='trellis2_candidate' else ['official'] for name in settings.tools.backends},
            'worker_concurrency': 1, 'active_timeout_s': settings.active_timeout_s,
            'max_tool_calls': settings.max_tool_calls, 'max_llm_calls': 4, 'max_llm_tokens': 12000}

    @app.get('/api/v1/printer-profiles')
    def profiles(): return list(service.profiles.values())

    @app.post('/api/v1/assets', status_code=201)
    async def upload(file: UploadFile = File(...), purpose: Literal['input', 'measurement', 'slicer_preview'] = 'input',
            run_id: UUID | None = None, mesh_version: Id | None = None):
        try:
            payload = await file.read(10485761)
            if purpose == 'slicer_preview':
                if run_id is None or mesh_version is None: raise ToolFailure('INVALID_ARGUMENT', '分层证据必须指定任务和网格版本')
                return service.upload_slice(run_id, mesh_version, payload, file.filename)
            if run_id is not None or mesh_version is not None:
                raise ToolFailure('INVALID_ARGUMENT', '原始图片/测量上传不接受网格版本')
            return service.assets.save(payload, file.filename)
        finally: await file.close()

    @app.post('/api/v1/model-tasks', status_code=202, response_model=ModelTaskResponse|GenerationTaskResponse)
    def create(body: CreateTask | ModelTaskRequest,
            idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None):
        return service.create(body, idempotency_key)

    @app.get('/api/v1/model-tasks/{run_id}', response_model=ModelTaskResponse|GenerationTaskResponse)
    def get(run_id: UUID): return service.store.row(run_id)['response']

    @app.get('/api/v1/model-tasks/{run_id}/runtime', response_model=RuntimeTask)
    def runtime(run_id: UUID):
        row = service.store.row(run_id)
        ctx = row['context']
        metrics=ctx.get('reconstruction_metrics')
        if metrics is None:
            metrics=next((op.get('result',{}).get('data',{}).get('model') for op in reversed(ctx.get('operations',[])) if op.get('operation')=='reconstruct'),None)
        pending = {k: v for k, v in ctx['pending'].items() if k != 'public_type'} if row['status'] == 'waiting_for_input' and ctx.get('pending') else None
        return {'response': row['response'], 'pending': pending,'artifact_frames':ctx.get('artifact_frames',{}),
            'resources': {'active_seconds': None if ctx.get('interrupted_active_seconds_unknown') else row['active_seconds'],
                'known_completed_active_seconds': row['active_seconds'], 'tool_calls': ctx['tool_calls'], 'llm': ctx['llm'],
                'reconstruction':metrics}}

    @app.get('/api/v1/model-tasks/{run_id}/events', response_model=EventsPage)
    def events(run_id: UUID, after: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=200)):
        entries = service.store.events(run_id, after, limit)
        return {'events': entries, 'next_after': entries[-1]['event_id'] if entries else after}

    @app.post('/api/v1/model-tasks/{run_id}/inputs', status_code=202, response_model=ModelTaskResponse|GenerationTaskResponse)
    def inputs(run_id: UUID, body: Submission):
        if body.kind == 'slicer': raise ToolFailure('INVALID_ARGUMENT', '切片结果请使用专用确认接口')
        return service.submit(run_id, body)

    @app.post('/api/v1/model-tasks/{run_id}/slicer-confirmation', status_code=202, response_model=ModelTaskResponse|GenerationTaskResponse)
    def slicer(run_id: UUID, body: Submission):
        if body.kind != 'slicer': raise ToolFailure('INVALID_ARGUMENT', '此接口仅接收切片确认')
        return service.submit(run_id, body)

    @app.post('/api/v1/model-tasks/{run_id}/cancel', response_model=ModelTaskResponse|GenerationTaskResponse)
    def cancel(run_id: UUID): return service.cancel(run_id)

    @app.get('/api/v1/model-tasks/{run_id}/artifacts/{artifact_id}')
    def artifact(run_id: UUID, artifact_id: Id):
        records = service.store.row(run_id)['response']['artifacts']
        found = next((a for a in records if a['artifact_id'] == artifact_id), None)
        if not found or found['kind'] == 'log':
            raise ToolFailure('REFERENCE_NOT_FOUND', '此任务没有可公开下载的该产物')
        try: path = resolve_artifact_path(service.store.root, found['relative_path'])
        except ValueError as exc: raise ToolFailure('REFERENCE_NOT_FOUND', '产物文件不存在或越界') from exc
        return FileResponse(path, filename=path.name)
    return app
