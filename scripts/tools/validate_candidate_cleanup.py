"""复用已生成候选，验证已允许的基础清理；不重建模型、不批准结构修改。"""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from image_to_3d_print.geometry.core import MeshStore
from image_to_3d_print.geometry.structure import StructureRequest,propose
from image_to_3d_print.inspection.service import InspectionConfig
from image_to_3d_print.schemas import ModelTaskRequest
from image_to_3d_print.tools import ToolFailure

def main():
    p=argparse.ArgumentParser();p.add_argument('--previous',type=Path,required=True);p.add_argument('--cloud-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    previous=json.loads(args.previous.read_text(encoding='utf-8'));run=previous['recovery']['tool']['run_id']
    store=MeshStore(ROOT);raw=previous['recovery']['tool']['data']['mesh_version']
    cleaned=store.clean(run,raw)
    report={'kind':'existing_candidate_basic_cleanup','clean':cleaned.model_dump(mode='json'),'gpu_used':False,'structural_modification_applied':False}
    (args.output/'partial.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:
        if not cleaned.tool.succeeded:raise ToolFailure(cleaned.tool.error.code,cleaned.tool.error.message)
        request=ModelTaskRequest(image_asset_id='candidate_development_fixture',height_value=80.,height_unit='mm',scale_source='user_target',
            orientation={'up_axis':'z','confirmed':True},printer_profile_id='demo_v1')
        scaled=store.scale(run,cleaned.tool.data['mesh_version'],request);report['scale']=scaled.model_dump(mode='json')
        if not scaled.tool.succeeded:raise ToolFailure(scaled.tool.error.code,scaled.tool.error.message)
        config=InspectionConfig(blender=args.cloud_root/'runtime/tools/blender-4.5.14-linux-x64/blender',addon_dir=args.cloud_root/'runtime/upstream/blender-addons')
        proposal=propose(ROOT,run,scaled.tool.data['mesh_version'],StructureRequest(operation='simplify',target_faces=100000),config)
        report.update(proposal=proposal.model_dump(mode='json'),status='proposal_not_applied')
    except ToolFailure as exc:report.update(status='blocked',error={'code':exc.code,'message':str(exc)})
    report['seconds']=time.perf_counter()-started
    (args.output/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'error':report.get('error'),'seconds':report['seconds']},ensure_ascii=False))

if __name__=='__main__':main()
