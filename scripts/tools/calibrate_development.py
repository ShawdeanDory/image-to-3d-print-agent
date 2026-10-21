"""仅对本轮真实TripoSR三个development输入核验公共视角。"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from PIL import Image
from image_to_3d_print.geometry.core import MeshStore,load_mesh
from image_to_3d_print.geometry.calibration import calibrate_development
from image_to_3d_print.measurement import normalize_mask,render_silhouette

def main():
    p=argparse.ArgumentParser();p.add_argument('--result',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    document=json.loads(args.result.read_text(encoding='utf-8'));cases=document['cases']
    if [case['case'] for case in cases]!=['block','pyramid','knob']:raise ValueError('固定两个拟合例和knob核验例，不临时换图')
    meshes=[];masks=[];store=MeshStore(ROOT)
    for case in cases:
        raw=store.get(case['run_id'],case['reconstruction']['tool']['data']['mesh_version'])
        if raw.parameters['backend']!='triposr':raise ValueError('不是所选后端版本')
        meshes.append(load_mesh(ROOT/raw.relative_path))
        mask=next(a for a in case['preprocess']['artifacts'] if a['artifact_id']==case['preprocess']['tool']['data']['mask_artifact_id'])
        with Image.open(ROOT/mask['relative_path']) as image:masks.append(image.copy())
    result=calibrate_development(meshes,masks)
    result.update(backend='triposr',upstream_revision='107cefdc244c39106fa830359024f6a2f1c78871',
        case_ids=['dev_n03','dev_n04','dev_n06'],raw_versions=[case['reconstruction']['tool']['data']['mesh_version'] for case in cases],
        human_review='pending',model_comparison=False)
    (args.output/'mapping.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    for index,(mesh,mask) in enumerate(zip(meshes,masks)):
        projection,_=render_silhouette(mesh.vertices,mesh.faces,result['rotation'])
        projection=normalize_mask(projection);mask=normalize_mask(mask)
        Image.merge('RGB',(mask,projection,Image.new('L',mask.size))).save(args.output/f'{cases[index]["case"]}-overlay.png')
    print(json.dumps({k:result[k] for k in ['status','selected','fitting_mean','validation_iou','quality_iou']},ensure_ascii=False))

if __name__=='__main__':main()
