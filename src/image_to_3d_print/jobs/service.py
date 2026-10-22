"""人工入口校验和幂等事务；此处不执行GPU/LLM。"""
from datetime import datetime, timezone
from uuid import uuid4, UUID
from pydantic import TypeAdapter
from ..runtime_contracts import Submission, CreateTask
from ..schemas import PrinterProfile
from ..schemas.task import ModelTaskRequest
from ..schemas.validation import validate_request_references, resolve_artifact_path
from ..image.assets import AssetStore
from ..tools import ToolFailure, ToolSession
from ..workflow.state import initial_context, response_for, save_context
from .store import Store, dumps

INPUTS = TypeAdapter(Submission)
TERMINAL = {'succeeded', 'failed', 'cancelled'}


class TaskService:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings.root)
        self.assets = AssetStore(self.store.root)
        self.profiles = {}
        for file in settings.profile_files:
            profile = PrinterProfile.model_validate_json(file.read_text(encoding='utf-8'))
            if profile.profile_id in self.profiles: raise ValueError('重复的打印配置ID')
            self.profiles[profile.profile_id] = profile

    def measurement(self, ctx, asset_id):
        asset = self.assets.get(asset_id)
        if any(e['evidence_id'] == asset_id for e in ctx['evidence']): return
        session = ToolSession(self.store.root, ctx['run_id'], 'preprocess')
        artifact = session.add('measurement', self.store.root / asset.relative_path, 'input_image')
        ctx['artifacts'].append(artifact.model_dump(mode='json'))
        ctx['evidence'].append({'evidence_id': asset_id, 'source_type': 'measurement',
            'source_id': asset_id, 'run_id': ctx['run_id'], 'mesh_version': None,
            'artifact_id': artifact.artifact_id, 'locator': 'user_uploaded_measurement',
            'created_at': datetime.now(timezone.utc).isoformat(), 'summary': '用户提供的实测尺度依据；真实性由用户确认'})

    def create(self, body, key=None):
        create = body if isinstance(body, CreateTask) else CreateTask(request=body)
        req = create.request
        automatic=self.settings.workflow_policy=='automatic_glb'
        if not automatic and (create.export_target_faces is not None or create.texture_size is not None):
            raise ToolFailure('INVALID_ARGUMENT','手动导出参数仅支持一次提交的自动GLB任务')
        if create.texture_size is not None and (create.backend or self.settings.default_backend)!='trellis2_candidate':
            raise ToolFailure('INVALID_ARGUMENT','TripoSR仅提供顶点色，纹理分辨率设置需要选择TRELLIS.2')
        if automatic and any(k!='orientation' for k in req.pending_inputs):
            raise ToolFailure('INVALID_ARGUMENT','首次提交请填完整高度、单位和尺度来源')
        if automatic and create.reconstruction_profile=='official' and (create.backend or self.settings.default_backend)=='trellis2_candidate':
            raise ToolFailure('INVALID_ARGUMENT','新任务仅使用快速生成，不再提供模式选择')
        orientation_source='user_parameter' if req.orientation.up_axis is not None else 'backend_z_up'
        if automatic and req.orientation.up_axis is None:
            req=ModelTaskRequest.model_validate({**req.model_dump(),'orientation':{'up_axis':'z','confirmed':False}})
        self.assets.get(req.image_asset_id)
        measurements = set()
        if req.scale_source == 'measured_object':
            self.assets.get(req.scale_evidence_id)
            measurements.add(req.scale_evidence_id)
        try: validate_request_references(req, {req.image_asset_id}, self.profiles, measurements)
        except ValueError as exc: raise ToolFailure('REFERENCE_NOT_FOUND', '图片、打印配置或测量依据未注册') from exc
        profile = self.profiles[req.printer_profile_id]
        ctx = initial_context(uuid4(), req.model_dump(mode='json'), profile.model_dump(mode='json'),
            create.backend or self.settings.default_backend)
        ctx['reconstruction_profile']=create.reconstruction_profile
        if automatic:
            ctx['export_options']={'export_target_faces':create.export_target_faces,'texture_size':create.texture_size}
            ctx['delivery_policy']='original-glb-v1'
            ctx['gpu_hole_policy']='gpu-boundary-fill-v1'
            if ctx['backend']=='trellis2_candidate' and self.settings.eye_texture_active:
                ctx['eye_texture_policy']='eye-local-v1'
        ctx['workflow_policy']=self.settings.workflow_policy
        if automatic:ctx['face_budget_policy']='image-complexity-v1'
        ctx['orientation_source']=orientation_source
        if automatic and ctx['backend']=='trellis2_candidate':ctx['reconstruction_profile']='course_fast'
        ctx['evidence_origin'] = 'test_fixture' if self.settings.confirmation_origin == 'test_fixture' else 'runtime'
        if measurements: self.measurement(ctx, req.scale_evidence_id)
        create_body=create.model_dump(mode='json')
        for name in ('reconstruction_profile','export_target_faces','texture_size'):
            if getattr(create,name) is None:create_body.pop(name,None)
        return self.store.create(ctx, response_for(ctx), create_body, key)['response']

    def validate_input(self, ctx, body):
        pending = ctx.get('pending')
        if ctx['status'] != 'waiting_for_input' or not pending:
            raise ToolFailure('STATE_CONFLICT', '任务当前没有等待此输入')
        if (body.pending_input_id != pending['pending_input_id'] or body.kind != pending['kind']
                or body.mesh_version != ctx['mesh_version']):
            raise ToolFailure('STATE_CONFLICT', '等待项、任务或网格版本不匹配')
        data = body.model_dump(mode='json')
        details = pending['details']
        if body.kind == 'constraints':
            request = dict(ctx['request'])
            if body.accept_suggestions:
                suggested = ctx.get('suggestions') or {}
                for name in ['height_value', 'height_unit', 'scale_source']:
                    if request.get(name) is None and suggested.get(name) is not None: request[name] = suggested[name]
                # 模型不能替用户确认姿态；必须在本次表单明确提交confirmed。
            for name in ['height_value', 'height_unit', 'scale_source', 'scale_evidence_id', 'orientation']:
                if data.get(name) is not None: request[name] = data[name]
            try: req = ModelTaskRequest.model_validate(request)
            except ValueError as exc: raise ToolFailure('INVALID_ARGUMENT', '补充后的尺度/测量依据/姿态不符合公共契约') from exc
            if req.scale_source == 'measured_object': self.assets.get(req.scale_evidence_id)
            if req.model_dump(mode='json') == ctx['request'] and not ctx.get('suggestions_unconfirmed'):
                raise ToolFailure('INVALID_ARGUMENT', '没有补充任何待确认约束')
            data['validated_request'] = req.model_dump(mode='json')
        elif body.kind == 'input_review':
            if body.foreground_artifact_id != details['foreground_artifact_id']:
                raise ToolFailure('STATE_CONFLICT', '图片确认必须对应当前前景')
        elif body.kind == 'print_review':
            if body.preview_artifact_id != details['preview_artifact_id']:
                raise ToolFailure('STATE_CONFLICT', '打印复核必须对应当前网格预览')
            if body.components_confirmed and body.component_count != details['component_count']:
                raise ToolFailure('STATE_CONFLICT', '组件数量与当前网格不符')
        elif body.kind == 'repair_request':
            if not body.stop and body.request is None:
                raise ToolFailure('INVALID_ARGUMENT', '须选择具体修复参数或停止')
            if body.request and body.request.operation not in details['allowed_operations']:
                raise ToolFailure('INVALID_ARGUMENT', '该网格没有此受支持的修复分支')
        elif body.kind == 'repair_confirmation':
            if body.proposal_id != details['proposal_id']:
                raise ToolFailure('STATE_CONFLICT', '提案不属于当前等待项')
        elif body.kind == 'slicer':
            if body.printer_profile_id != ctx['profile']['profile_id'] or body.slicer_version != ctx['profile']['slicer_version']:
                raise ToolFailure('STATE_CONFLICT', '切片软件或打印配置版本不匹配')
            artifact = next((a for a in ctx['artifacts'] if a['artifact_id'] == body.layer_preview_asset_id), None)
            if not artifact or artifact['kind'] != 'slicer_preview' or artifact['mesh_version'] != body.mesh_version:
                raise ToolFailure('REFERENCE_NOT_FOUND', '缺少本任务当前网格的分层图片证据')
            resolve_artifact_path(self.store.root, artifact['relative_path'])
            if body.result == 'pass':
                if not all([body.model_preview_confirmed, body.bed_confirmed, body.support_reviewed]):
                    raise ToolFailure('INVALID_ARGUMENT', '须实际复核模型预览、底面和支撑')
                expected = ctx['inspection']['dimensions_mm']
                tolerance = max(.5, ModelTaskRequest.model_validate(ctx['request']).height_mm * .01)
                if any(abs(a-b) > tolerance for a, b in zip(expected, body.dimensions_mm)):
                    raise ToolFailure('INVALID_ARGUMENT', '切片尺寸与独立重读网格不匹配')
                overhang = next(c for c in ctx['inspection']['checks'] if c['name'] == 'overhang')
                if overhang['status'] == 'warn' and not body.supports_enabled:
                    raise ToolFailure('INVALID_ARGUMENT', '存在悬垂警告，需要启用并复核支撑')
        return data

    def submit(self, run, body):
        body = INPUTS.validate_python(body)
        raw = body.model_dump(mode='json')
        with self.store.transaction() as db:
            row = self.store.row(run, db)
            old = db.execute('SELECT body FROM submissions WHERE run=? AND (submission_id=? OR pending_id=?)',
                (str(run), body.submission_id, body.pending_input_id)).fetchone()
            if old:
                import json
                previous = json.loads(old['body'])
                comparable = {k: v for k, v in previous.items() if k not in {'submission_id', 'validated_request'}}
                if comparable != {k: v for k, v in raw.items() if k != 'submission_id'}:
                    raise ToolFailure('STATE_CONFLICT', '此提交ID或等待项已接受不同输入')
                return row['response']
            ctx = row['context']
            data = self.validate_input(ctx, body)
            db.execute('INSERT INTO submissions(run,submission_id,pending_id,body) VALUES(?,?,?,?)',
                (str(run), body.submission_id, body.pending_input_id, dumps(data)))
            # 检查点保留原pending，供runner定位Command.resume；公共排队响应不携带等待字段。
            queued = dict(ctx, status='queued', pending=None)
            response = response_for(queued)
            db.execute("UPDATE tasks SET status='queued',response=? WHERE run=?", (dumps(response), str(run)))
            self.store.event(db, run, 'input_submitted', queued, {'submission_id': body.submission_id})
            return response

    def cancel(self, run):
        with self.store.transaction() as db:
            row = self.store.row(run, db)
            if row['status'] in TERMINAL or row['status'] == 'cancel_requested': return row['response']
            ctx = row['context']
            ctx.update(status='cancel_requested' if row['status'] == 'running' else 'cancelled', pending=None, error=None)
            response = response_for(ctx)
            db.execute('UPDATE tasks SET status=?,context=?,response=? WHERE run=?',
                (ctx['status'], dumps(ctx), dumps(response), str(run)))
            self.store.event(db, run, 'cancel', ctx)
            return response

    def upload_slice(self, run, mesh_version, payload, filename):
        with self.store.transaction() as db:
            row = self.store.row(run, db)
            ctx = row['context']
            if (row['status'] != 'waiting_for_input' or not ctx.get('pending')
                    or ctx['pending']['kind'] != 'slicer' or ctx['mesh_version'] != mesh_version):
                raise ToolFailure('STATE_CONFLICT', '只允许为当前等待切片的网格上传分层证据')
            asset = self.assets.save(payload, filename)
            session = ToolSession(self.store.root, run, 'slice', mesh_version)
            artifact = session.add('layers', self.store.root / asset.relative_path, 'slicer_preview')
            ctx['artifacts'].append(artifact.model_dump(mode='json'))
            response = response_for(ctx)
            db.execute('UPDATE tasks SET context=?,response=? WHERE run=?', (dumps(ctx), dumps(response), str(run)))
            self.store.event(db, run, 'slicer_evidence_uploaded', ctx, {'artifact_id': artifact.artifact_id})
            return {'asset': asset.model_dump(mode='json'), 'artifact': artifact.model_dump(mode='json')}
