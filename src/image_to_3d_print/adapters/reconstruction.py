import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import time
from typing import Literal
from uuid import UUID
from pydantic import Field
from PIL import Image
from ..image.assets import InputReview
from ..schemas.common import ContractModel
from ..schemas.validation import resolve_artifact_path
from ..geometry.core import MeshStore,load_mesh,topology
from ..tools import ToolFailure,ToolSession,digest,stop_process_group

REVISIONS={'triposr':'107cefdc244c39106fa830359024f6a2f1c78871','trellis2_candidate':'75fbf0183001ed9876c8dbb35de6b68552ee08bd'}

class BackendConfig(ContractModel):
    backend: Literal['triposr','trellis2_candidate']
    python: Path
    execution_root: Path
    timeout_s: float=Field(default=300,gt=0,le=300)
    seed: int=0
    pipeline_type: Literal['1024_cascade']='1024_cascade'
    mc_resolution: Literal[128]=128
    device: Literal['cuda:0']='cuda:0'
    trellis_output_variant: Literal['native_geometry']='native_geometry'

def execute_worker(config,mode,input_path,output,script,cancel_event=None):
    if os.name!='posix':raise ToolFailure('TOOL_UNAVAILABLE','本轮适配器只验证Linux进程组停止，不能静默在Windows运行')
    if not config.python.is_file():raise ToolFailure('MODEL_NOT_CONFIGURED','未找到所选后端Python环境')
    source_name='TripoSR' if config.backend=='triposr' else 'TRELLIS.2'
    source=config.execution_root/'runtime/upstream'/source_name
    try:
        revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.CalledProcessError) as exc:raise ToolFailure('MODEL_NOT_CONFIGURED','固定后端源码不存在') from exc
    if revision!=REVISIONS[config.backend]:raise ToolFailure('MODEL_NOT_CONFIGURED','所选后端源码版本与锁定不符')
    watchdog=shutil.which('timeout')
    if watchdog is None:raise ToolFailure('TOOL_UNAVAILABLE','Linux缺少工具超时守护程序')
    argv=[str(config.python),str(script),'--mode',mode,'--root',str(config.execution_root),'--backend',config.backend,
        '--input',str(input_path),'--output',str(output),'--seed',str(config.seed)]
    argv=[watchdog,'--signal=TERM','--kill-after=5s',f'{config.timeout_s}s',*argv]
    environment={**os.environ,'HF_HOME':str(config.execution_root/'runtime/cache/huggingface'),
        'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','CUDA_VISIBLE_DEVICES':'0','OPENCV_IO_ENABLE_OPENEXR':'1',
        'PYTORCH_CUDA_ALLOC_CONF':'expandable_segments:True','OMP_NUM_THREADS':'4'}
    environment.pop('PYTHONPATH',None);environment.pop('PYTHONHOME',None)
    log=output/'process.log';started=time.perf_counter()
    with log.open('w',encoding='utf-8') as stream:
        process=subprocess.Popen(argv,stdout=stream,stderr=subprocess.STDOUT,env=environment,start_new_session=True)
        reason=None
        try:
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():reason=('STATE_CONFLICT','任务已取消')
                elif time.perf_counter()-started>config.timeout_s:reason=('TOOL_TIMEOUT','模型工具执行超时')
                if reason:
                    try:os.killpg(process.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:stop_process_group(process)
                    break
                time.sleep(.1)
        except BaseException:
            stop_process_group(process)
            raise
    execution={'backend':config.backend,'upstream_revision':revision,'exit_code':process.returncode,
        'process_wall_seconds':time.perf_counter()-started,'seed':config.seed,'entry':'model_worker.py',
        'machine':'configured_linux_instance','device':config.device,'offline':True,'automatic_retries':0,'input_sha256':digest(input_path)}
    (output/'execution.json').write_text(json.dumps(execution,indent=2)+'\n',encoding='utf-8')
    if reason:raise ToolFailure(*reason)
    if process.returncode==124:raise ToolFailure('TOOL_TIMEOUT','模型工具达到系统守护时限')
    if process.returncode:
        text=log.read_text(encoding='utf-8')[-10000:].lower()
        code='GPU_OUT_OF_MEMORY' if 'out of memory' in text else 'TOOL_UNAVAILABLE' if 'cuda_unavailable' in text else 'INVALID_ARGUMENT'
        raise ToolFailure(code,'所选模型工具失败，详细信息保留在本任务日志')
    return execution

class ReconstructionAdapter:
    def __init__(self,root,config:BackendConfig|None):self.root=Path(root).resolve();self.config=config

    def reconstruct(self,run_id,prepared,review:InputReview,cancel_event=None):
        session=ToolSession(self.root,run_id,'reconstruct')
        try:
            if self.config is None:raise ToolFailure('MODEL_NOT_CONFIGURED','必须显式选择后端、环境和执行机器')
            if prepared.tool.run_id!=UUID(str(run_id)) or not prepared.tool.succeeded:
                raise ToolFailure('STATE_CONFLICT','前景不属于本任务或准备失败')
            if (not review.accepted or review.asset_id!=prepared.tool.data.get('asset_id')
                or review.foreground_artifact_id!=prepared.tool.data.get('foreground_artifact_id')):
                raise ToolFailure('STATE_CONFLICT','先复核本图前景、完整性及简单摆件适用范围')
            fg=next(a for a in prepared.artifacts if a.artifact_id==review.foreground_artifact_id)
            input_path=resolve_artifact_path(self.root,fg.relative_path)
            (session.directory/'invocation.json').write_text(json.dumps({'run_id':str(run_id),'backend':self.config.backend,
                'input_asset_id':review.asset_id,'foreground_artifact_id':fg.artifact_id,'input_sha256':digest(input_path),'review':review.model_dump()},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            script=Path(__file__).resolve().parents[3]/'scripts/tools/model_worker.py'
            execution=execute_worker(self.config,'reconstruct',input_path,session.directory,script,cancel_event)
            raw=session.directory/'raw_mesh.ply'
            mesh=load_mesh(raw)
            metadata=json.loads((session.directory/'model.json').read_text(encoding='utf-8'))
            version=MeshStore(self.root).import_mesh(raw.relative_to(self.root).as_posix(),run_id,parameters={
                'backend':self.config.backend,'input_asset_id':review.asset_id,'coordinate_system':'z_up_unitless',
                'input_view_mapping':'unverified_until_development_calibration','execution':execution})
            session.mesh_version=version.mesh_version
            session.add('raw_mesh',self.root/version.relative_path,'raw_mesh','unitless')
            return session.finish({'mesh_version':version.mesh_version,'version_record':version.model_dump(mode='json'),
                'initial_geometry':topology(mesh),'execution':execution,'model':metadata,'input_review':review.model_dump(), 'printability':'not_evaluated'})
        except ToolFailure as exc:return session.fail(exc.code,str(exc))
        except (OSError,ValueError,StopIteration) as exc:return session.fail('INVALID_ARGUMENT','模型产物或输入引用无效')

    def remove_background(self,source,output):
        if self.config is None or self.config.backend!='trellis2_candidate':
            raise ToolFailure('MODEL_NOT_CONFIGURED','RMBG需要显式已有TRELLIS.2环境')
        script=Path(__file__).resolve().parents[3]/'scripts/tools/model_worker.py'
        execute_worker(self.config,'background',source,output,script)
        with Image.open(output/'background_removed.png') as image:return image.copy()

    def recover_generated(self,run_id,previous_outcome):
        """接续已成功生成但接入失败的同任务产物，不重新调用GPU。"""
        session=ToolSession(self.root,run_id,'reconstruct')
        try:
            from ..tools import ToolOutcome
            if self.config is None:raise ToolFailure('MODEL_NOT_CONFIGURED','缺显式后端配置')
            file=resolve_artifact_path(self.root,previous_outcome)
            if not file.is_relative_to(self.root/f'runs/{UUID(str(run_id))}/tools'):
                raise ToolFailure('STATE_CONFLICT','恢复入口不属于本任务')
            previous=ToolOutcome.model_validate_json(file.read_text(encoding='utf-8'))
            execution=json.loads((file.parent/'execution.json').read_text(encoding='utf-8'))
            metadata=json.loads((file.parent/'model.json').read_text(encoding='utf-8'))
            if (previous.tool.run_id!=UUID(str(run_id)) or execution['exit_code']!=0 or execution['backend']!=self.config.backend
                or execution['upstream_revision']!=REVISIONS[self.config.backend]):raise ToolFailure('STATE_CONFLICT','原执行未成功或版本不匹配')
            raw=file.parent/'raw_mesh.ply';mesh=load_mesh(raw)
            version=MeshStore(self.root).import_mesh(raw.relative_to(self.root).as_posix(),run_id,parameters={
                'backend':self.config.backend,'coordinate_system':'z_up_unitless','recovered_from':previous_outcome,'execution':execution})
            session.mesh_version=version.mesh_version
            session.add('raw_mesh',self.root/version.relative_path,'raw_mesh','unitless')
            session.add('original_model_log',file.parent/'process.log','log')
            return session.finish({'mesh_version':version.mesh_version,'version_record':version.model_dump(mode='json'),
                'initial_geometry':topology(mesh),'model':metadata,'gpu_called_this_operation':False,
                'needs_simplification_confirmation':len(mesh.faces)>100000,'printability':'not_evaluated'})
        except ToolFailure as exc:return session.fail(exc.code,str(exc))
        except (OSError,ValueError,KeyError) as exc:return session.fail('INVALID_ARGUMENT','原模型产物或执行记录无效')
