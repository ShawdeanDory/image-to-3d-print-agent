"""对已生成的具体版本/提案做CPU诊断图，不批准结构操作。"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from image_to_3d_print.inspection.service import InspectionConfig,preview_mesh,blender_call
from image_to_3d_print.geometry.core import load_mesh

def main():
    p=argparse.ArgumentParser();p.add_argument('--models',type=Path,required=True);p.add_argument('--large',type=Path,required=True)
    p.add_argument('--cloud-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False)
    config=InspectionConfig(blender=args.cloud_root/'runtime/tools/blender-4.5.14-linux-x64/blender',addon_dir=args.cloud_root/'runtime/upstream/blender-addons')
    records=[]
    for case in json.loads(args.models.read_text(encoding='utf-8'))['cases']:
        result=preview_mesh(ROOT,case['run_id'],case['scale']['tool']['data']['mesh_version'],config)
        records.append({'case':case['case'],'outcome':result.model_dump(mode='json')})
    large=json.loads(args.large.read_text(encoding='utf-8'));proposal=large['proposal']
    target=args.output/'candidate';target.mkdir()
    result=blender_call(config,'preview',load_mesh(ROOT/proposal['preview_path']),target,{'unit':'mm'})
    records.append({'case':'large_proposal_only','proposal_id':proposal['proposal_id'],'image':str((target/'preview.png').relative_to(ROOT)),
        'metadata':result,'structural_modification_applied':False})
    (args.output/'validation.json').write_text(json.dumps({'previews':records,'gpu_used':False,'human_acceptance':False},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'previews':len(records),'gpu_used':False}))

if __name__=='__main__':main()
