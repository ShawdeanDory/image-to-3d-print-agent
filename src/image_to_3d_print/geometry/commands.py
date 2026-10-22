"""供工作流调用的统一工具门面；不包含HTTP和Agent状态机。"""
from pathlib import Path
import hashlib
from typing import Annotated,Literal,Union
from uuid import UUID
from pydantic import Field,TypeAdapter,model_validator,StrictBool
from ..schemas.common import ContractModel,Id,RelativePath,Text
from ..schemas.task import ModelTaskRequest
from ..schemas.validation import resolve_artifact_path
from ..schemas import PrinterProfile
from ..tools import ToolSession,ToolFailure,ToolOutcome
from ..image.assets import AssetStore,InputReview,AutomaticInputAcceptance
from ..image.complexity import analyze_image
from ..adapters.reconstruction import BackendConfig,ReconstructionAdapter
from ..inspection.service import InspectionConfig,BedReview,ComponentReview,inspect_mesh,preview_mesh
from ..artifacts.export import export_mesh,export_preview
from .core import MeshStore
from .structure import StructureRequest,propose,confirm,apply_proposal
from .view import measure_view

class Call(ContractModel):run_id:UUID
class ImportCall(Call):
    operation:Literal['import_image']
    source:RelativePath
class ComplexityCall(Call):
    operation:Literal['analyze_complexity']
    asset_id:Id
class PrepareCall(Call):
    operation:Literal['prepare_image']
    asset_id:Id
    background_backend:Literal['trellis2_candidate']|None=None
    preprocessing:Literal['legacy_foreground','official_input']='legacy_foreground'
class ReconstructCall(Call):
    operation:Literal['reconstruct']
    backend:Literal['triposr','trellis2_candidate']
    prepared_outcome:RelativePath
    review:InputReview|AutomaticInputAcceptance
    reconstruction_profile:Literal['official','course_fast']|None=None
class MeshCall(Call):
    operation:Literal['clean','export','export_glb','preview']
    mesh_version:Id
class ScaleCall(Call):
    operation:Literal['scale']
    mesh_version:Id
    request:ModelTaskRequest
class InspectCall(Call):
    operation:Literal['inspect']
    mesh_version:Id
    profile:PrinterProfile
    height_mm:float|None=Field(default=None,gt=0)
    bed_review:BedReview|None=None
    component_review:ComponentReview|None=None
class ProposeCall(Call):
    operation:Literal['propose']
    mesh_version:Id
    request:StructureRequest
    adaptive_budget:StrictBool=False
class ConfirmCall(Call):
    operation:Literal['confirm']
    proposal_id:Id
    reviewer:Text
    accepted:bool
class ApplyCall(Call):
    operation:Literal['apply']
    proposal_id:Id
class MeasureCall(Call):
    operation:Literal['measure_view']
    mesh_version:Id
    mask_path:RelativePath
    backend:Literal['triposr','trellis2_candidate']

Command=Annotated[Union[ImportCall,ComplexityCall,PrepareCall,ReconstructCall,MeshCall,ScaleCall,InspectCall,ProposeCall,ConfirmCall,ApplyCall,MeasureCall],Field(discriminator='operation')]
COMMANDS=TypeAdapter(Command)

class ToolConfiguration(ContractModel):
    backends:dict[Literal['triposr','trellis2_candidate'],BackendConfig]=Field(default_factory=dict)
    inspection:InspectionConfig|None=None
    view_mappings:dict[Literal['triposr','trellis2_candidate'],RelativePath]=Field(default_factory=dict)

    @model_validator(mode='after')
    def backend_keys_match(self):
        if any(key!=value.backend for key,value in self.backends.items()):raise ValueError('后端注册键与实际配置不一致，不能静默换模型')
        return self

def dispatch(root,command,configuration:ToolConfiguration,cancel_event=None,*,human_action=False,confirmation_origin='human',automatic_input=False,automatic_action=False):
    root=Path(root).resolve();command=COMMANDS.validate_python(command)
    store=MeshStore(root);assets=AssetStore(root);op=command.operation;run=command.run_id
    tool_name={'analyze_complexity':'preprocess','import_image':'preprocess','prepare_image':'preprocess','propose':'repair','confirm':'repair','apply':'repair','clean':'repair','scale':'repair','inspect':'inspect','export':'export','export_glb':'export','preview':'inspect','measure_view':'inspect','reconstruct':'reconstruct'}[op]
    # 包装只有原子返回值的资产/提案接口；已有ToolOutcome直接返回。
    session=None
    try:
        if confirmation_origin not in {'human','test_fixture','automatic_policy'} or (confirmation_origin=='automatic_policy' and not automatic_action):
            raise ToolFailure('INVALID_ARGUMENT','服务端确认来源无效')
        if op=='propose' and command.adaptive_budget and not (automatic_action and confirmation_origin=='automatic_policy'):
            raise ToolFailure('STATE_CONFLICT','低面数预算只能由已启用的服务端自动策略批准')
        if op=='confirm' and human_action is not True and not (automatic_action and confirmation_origin=='automatic_policy'):
            raise ToolFailure('STATE_CONFLICT','结构修改确认只能由已核对当前等待项的人工接口提交，不能由模型工具自行批准')
        if op=='reconstruct' and isinstance(command.review,AutomaticInputAcceptance) and automatic_input is not True:
            raise ToolFailure('STATE_CONFLICT','自动图片继续仅允许服务端已启用的政策调用')
        needs_confirmation=(op=='reconstruct' and isinstance(command.review,InputReview) and command.review.decision=='accepted' or
            op=='scale' and not command.request.pending_inputs or
            op=='inspect' and any(review is not None and review.confirmed for review in [command.bed_review,command.component_review]))
        if needs_confirmation and human_action is not True and not (automatic_action and confirmation_origin=='automatic_policy'):
            raise ToolFailure('STATE_CONFLICT','图片、姿态或打印复核须由服务端核对实际人工输入后调用，模型不能自行声明已确认')
        if op=='analyze_complexity':
            from PIL import Image
            session=ToolSession(root,run,tool_name)
            asset=assets.get(command.asset_id);path=resolve_artifact_path(root,asset.relative_path)
            with Image.open(path) as image:analysis=analyze_image(image)
            return session.finish({'asset_id':command.asset_id,'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'analysis':analysis.model_dump(mode='json')})
        if op=='import_image':
            session=ToolSession(root,run,tool_name)
            source=resolve_artifact_path(root,command.source);asset=assets.save(source.read_bytes(),source.name)
            session.add('input',root/asset.relative_path,'input_image')
            return session.finish({'asset':asset.model_dump(mode='json')})
        if op=='prepare_image':
            config=configuration.backends.get(command.background_backend) if command.background_backend else None
            return assets.prepare(command.asset_id,run,ReconstructionAdapter(root,config).remove_background if config else None,command.preprocessing)
        if op=='reconstruct':
            prepared=ToolOutcome.model_validate_json(resolve_artifact_path(root,command.prepared_outcome).read_text(encoding='utf-8'))
            config=configuration.backends.get(command.backend)
            if command.reconstruction_profile is not None:
                if config is None:raise ToolFailure('MODEL_NOT_CONFIGURED','所选后端没有配置，不自动换模型')
                config=BackendConfig.model_validate({**config.model_dump(),'inference_profile':command.reconstruction_profile})
            return ReconstructionAdapter(root,config).reconstruct(run,prepared,command.review,cancel_event,automatic_input=automatic_input)
        if op=='clean':return store.clean(run,command.mesh_version,count_repair_round=not automatic_action)
        if op=='scale':return store.scale(run,command.mesh_version,command.request,automatic_orientation=automatic_action)
        if op=='inspect':return inspect_mesh(root,run,command.mesh_version,command.profile,command.height_mm,command.bed_review,configuration.inspection,command.component_review,automatic_bed=automatic_action)
        if op=='export':return export_mesh(root,run,command.mesh_version,configuration.inspection)
        if op=='export_glb':return export_preview(root,run,command.mesh_version,configuration.inspection)
        if op=='preview':return preview_mesh(root,run,command.mesh_version,configuration.inspection)
        if op=='measure_view':return measure_view(root,run,command.mesh_version,command.mask_path,command.backend,configuration.view_mappings.get(command.backend))
        if op=='apply':return apply_proposal(root,run,command.proposal_id)
        session=ToolSession(root,run,tool_name,getattr(command,'mesh_version',None))
        if op=='propose':
            record=propose(root,run,command.mesh_version,command.request,configuration.inspection,adaptive_budget=command.adaptive_budget)
            session.add('preview',root/record.preview_path,'repaired_mesh')
            session.add('preview_glb',root/record.preview_glb_path,'repaired_mesh')
            return session.finish({'proposal':record.model_dump(mode='json'),'pending_input_type':'repair_confirmation'})
        data=confirm(root,run,command.proposal_id,command.reviewer,command.accepted,origin=confirmation_origin)
        session.add('confirmation',root/f'runs/{run}/proposals/{command.proposal_id}/confirmation.json','inspection_report')
        return session.finish({'confirmation':data,'next_step':'apply' if command.accepted else 'stop_or_revise'})
    except ToolFailure as exc:
        session=session or ToolSession(root,run,tool_name,getattr(command,'mesh_version',None))
        return session.fail(exc.code,str(exc))
    except (OSError,ValueError) as exc:
        session=session or ToolSession(root,run,tool_name,getattr(command,'mesh_version',None))
        return session.fail('INVALID_ARGUMENT','工具输入或文件引用无效')
