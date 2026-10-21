"""开发图片的真实动态重建冒烟；不执行正式后端比较或保留集。"""
import argparse,io,json,os,sys,time
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from PIL import Image
from image_to_3d_print.image.assets import AssetStore,InputReview
from image_to_3d_print.adapters.reconstruction import BackendConfig,ReconstructionAdapter
from image_to_3d_print.geometry.core import MeshStore
from image_to_3d_print.inspection.service import InspectionConfig,inspect_mesh
from image_to_3d_print.artifacts.export import export_mesh
from image_to_3d_print.schemas import ModelTaskRequest,PrinterProfile

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cloud-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--backend',choices=['triposr','trellis2_candidate'],required=True);parser.add_argument('--cases',nargs='+',choices=['block','pyramid','knob'],required=True)
    parser.add_argument('--jpeg-background',action='store_true');args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    name='triposr' if args.backend=='triposr' else 'trellis2'
    config=BackendConfig(backend=args.backend,python=args.cloud_root/f'runtime/envs/{name}/bin/python',execution_root=args.cloud_root)
    adapter=ReconstructionAdapter(ROOT,config);assets=AssetStore(ROOT);store=MeshStore(ROOT)
    inspection_config=InspectionConfig(blender=args.cloud_root/'runtime/tools/blender-4.5.14-linux-x64/blender',addon_dir=args.cloud_root/'runtime/upstream/blender-addons')
    profile=PrinterProfile.model_validate_json((ROOT/'fixtures/p1/printer_profile.json').read_text())
    reports=[];started=time.perf_counter()
    for case in args.cases:
        run=uuid4();original=ROOT/f'fixtures/p1/procedural/{case}.png';payload=original.read_bytes();filename=case+'.png'
        if args.jpeg_background:
            with Image.open(original) as image:
                image=image.convert('RGBA');background=Image.new('RGBA',image.size,'white');background.alpha_composite(image)
                stream=io.BytesIO();background.convert('RGB').save(stream,format='JPEG');payload=stream.getvalue();filename=case+'.jpg'
        asset=assets.save(payload,filename)
        background_config=BackendConfig(backend='trellis2_candidate',python=args.cloud_root/'runtime/envs/trellis2/bin/python',execution_root=args.cloud_root)
        background_adapter=ReconstructionAdapter(ROOT,background_config)
        prepared=assets.prepare(asset.asset_id,run,background_runner=background_adapter.remove_background if args.jpeg_background else None)
        case_record={'case':case,'run_id':str(run),'asset':asset.model_dump(mode='json'),'preprocess':prepared.model_dump(mode='json'),
            'input_review_scope':'AI viewed repository development fixture, not human acceptance','backend':args.backend}
        if not prepared.tool.succeeded:
            reports.append(case_record);break
        review=InputReview(asset_id=asset.asset_id,foreground_artifact_id=prepared.tool.data['foreground_artifact_id'],decision='accepted',
            reviewer='authorized_development_fixture_runner',origin='test_fixture',complete_subject=True,simple_nonfunctional_ornament=True,foreground_correct=True)
        result=adapter.reconstruct(run,prepared,review)
        case_record['reconstruction']=result.model_dump(mode='json')
        if result.tool.succeeded:
            raw=result.tool.data['mesh_version'];clean=store.clean(run,raw);case_record['clean']=clean.model_dump(mode='json')
            if clean.tool.succeeded:
                request=ModelTaskRequest(image_asset_id=asset.asset_id,height_value=80.,height_unit='mm',scale_source='user_target',
                    orientation={'up_axis':'z','confirmed':True},printer_profile_id=profile.profile_id,description='开发fixture工具验证；80毫米为测试目标，不是实测尺度')
                scaled=store.scale(run,clean.tool.data['mesh_version'],request);case_record['scale']=scaled.model_dump(mode='json')
                if scaled.tool.succeeded:
                    version=scaled.tool.data['mesh_version']
                    case_record['inspection']=inspect_mesh(ROOT,run,version,profile,height_mm=80.,config=inspection_config).model_dump(mode='json')
                    case_record['export']=export_mesh(ROOT,run,version).model_dump(mode='json')
        reports.append(case_record)
        (args.output/'validation.json').write_text(json.dumps({'kind':'real_development_image_tool_chain','cases':reports,'seconds':time.perf_counter()-started,
            'model_comparison':False,'holdout_executed':False,'human_acceptance':'pending','physical_printing':False},ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps({'case':case,'reconstruction':result.tool.succeeded,'error':result.tool.error.model_dump() if result.tool.error else None,'run_id':str(run)}),flush=True)
    if not (args.output/'validation.json').exists():
        (args.output/'validation.json').write_text(json.dumps({'cases':reports,'error':'preprocess_failed'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return not all('reconstruction' in item and item['reconstruction']['tool']['succeeded'] for item in reports)

if __name__=='__main__':raise SystemExit(main())
