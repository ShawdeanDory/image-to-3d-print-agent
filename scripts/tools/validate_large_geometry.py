"""接续已生成大网格，只读恢复及确认前提案，不调用GPU或自动批准。"""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from image_to_3d_print.adapters.reconstruction import BackendConfig,ReconstructionAdapter
from image_to_3d_print.geometry.core import MeshStore
from image_to_3d_print.geometry.structure import StructureRequest,propose
from image_to_3d_print.inspection.service import InspectionConfig
from image_to_3d_print.schemas import ModelTaskRequest
from image_to_3d_print.tools import ToolFailure

def main():
    p=argparse.ArgumentParser();p.add_argument('--result',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cloud-root',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    case=json.loads(args.result.read_text(encoding='utf-8'))['cases'][0];run=case['run_id']
    previous=next(a['relative_path'] for a in case['reconstruction']['artifacts'] if a['artifact_id'].endswith('_report'))
    previous=str(Path(previous).parent/'outcome.json')
    config=BackendConfig(backend='trellis2_candidate',python=args.cloud_root/'runtime/envs/trellis2/bin/python',execution_root=args.cloud_root)
    recovered=ReconstructionAdapter(ROOT,config).recover_generated(run,previous)
    report={'kind':'existing_large_mesh_recovery_and_proposal','recovery':recovered.model_dump(mode='json'),'gpu_used':False,'structural_modification_applied':False}
    try:
        if not recovered.tool.succeeded:raise ToolFailure(recovered.tool.error.code,recovered.tool.error.message)
        request=ModelTaskRequest(image_asset_id=case['asset']['asset_id'],height_value=80.,height_unit='mm',scale_source='user_target',
            orientation={'up_axis':'z','confirmed':True},printer_profile_id='demo_v1',description='开发fixture80毫米测试目标；不是人工验收')
        scaled=MeshStore(ROOT).scale(run,recovered.tool.data['mesh_version'],request);report['scale']=scaled.model_dump(mode='json')
        if not scaled.tool.succeeded:raise ToolFailure(scaled.tool.error.code,scaled.tool.error.message)
        inspection=InspectionConfig(blender=args.cloud_root/'runtime/tools/blender-4.5.14-linux-x64/blender',addon_dir=args.cloud_root/'runtime/upstream/blender-addons')
        proposal=propose(ROOT,run,scaled.tool.data['mesh_version'],StructureRequest(operation='simplify',target_faces=100000),inspection)
        report['proposal']=proposal.model_dump(mode='json');report['status']='waiting_for_specific_human_confirmation'
    except ToolFailure as exc:report.update(status='blocked',error={'code':exc.code,'message':str(exc)})
    report['seconds']=time.perf_counter()-started
    (args.output/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'error':report.get('error'),'seconds':report['seconds']},ensure_ascii=False))

if __name__=='__main__':main()
