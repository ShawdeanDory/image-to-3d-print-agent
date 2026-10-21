"""同一云端开发图片实测；独立存储，不批准打印/结构/切片。"""
import argparse,json,time
from pathlib import Path
import numpy as np
from image_to_3d_print.jobs.config import Settings
from image_to_3d_print.jobs.service import TaskService
from image_to_3d_print.jobs.worker import Worker
from image_to_3d_print.runtime_contracts import CreateTask
from image_to_3d_print.geometry.core import MeshStore,load_mesh,topology
from image_to_3d_print.inspection.service import inspect_mesh
from image_to_3d_print.schemas.common import MeshInspection


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True);args=parser.parse_args()
    project=args.project.resolve();directory=project/'runs/course-fast-20261021-01';directory.mkdir(exist_ok=True)
    original=json.loads((project/'runtime/config/backend.json').read_text())
    production=TaskService(Settings.model_validate(original))
    asset=production.assets.get('a_f727e3f9b1a24d999c4e38d616ce5cf8')
    content=(production.store.root/asset.relative_path).read_bytes()
    import hashlib
    if hashlib.sha256(content).hexdigest()!='1d6ac093c18648fc9568f58e310db3d1666d942cb0a2ea36b21be8384993f4ff':
        raise ValueError('开发原图摘要不一致，拒绝换图')
    config={**original,'root':str(directory/'application'),'llm':{},'input_review_policy':'automatic'}
    settings=Settings.model_validate(config);service=TaskService(settings)
    copied=service.assets.save(content,'duck.jpg')
    body=CreateTask(request={'image_asset_id':copied.asset_id,'printer_profile_id':'demo_v1',
        'height_value':10.,'height_unit':'cm','scale_source':'user_target','orientation':{'up_axis':'z','confirmed':True}},
        backend='trellis2_candidate',reconstruction_profile='course_fast')
    run=service.create(body,'course-fast-same-duck')['run_id']
    (directory/'run-id.txt').write_text(run)
    print(json.dumps({'run_id':run,'status':'started','storage':'isolated_development_validation'}),flush=True)
    started=time.perf_counter();Worker(settings).serve(once=True)
    row=service.store.row(run);ctx=row['context']
    result={'run_id':run,'status':row['status'],'pending':(ctx.get('pending') or {}).get('kind'),'error':ctx.get('error'),
        'wall_seconds':time.perf_counter()-started,'input_sha256':hashlib.sha256(content).hexdigest(),'model':ctx.get('reconstruction_metrics'),
        'human_reviews':ctx.get('human_reviews',[]),'operations':[item['operation'] for item in ctx['operations']]}
    if ctx.get('mesh_version'):
        record=MeshStore(settings.root).get(run,ctx['mesh_version']);mesh=load_mesh(settings.root/record.relative_path)
        result.update(mesh_version=record.mesh_version,geometry=topology(mesh),visual_kind=mesh.visual.kind,
            color_range=np.ptp(mesh.visual.vertex_colors[:,:3].astype(int),axis=0).tolist() if mesh.visual.kind=='vertex' else None)
        inspection=inspect_mesh(settings.root,run,record.mesh_version,service.profiles['demo_v1'],100.,config=settings.tools.inspection)
        data=inspection.tool.data.get('inspection') or {}
        result['inspection']={key:data.get(key) for key in ['ready_for_print','mesh_version','dimensions_mm','component_count']}
        result['inspection']['ready_for_print']=MeshInspection.model_validate(data).ready_for_print if data else None
        result['inspection']['checks']=[{k:item.get(k) for k in ['name','status','value','threshold']} for item in data.get('checks',[])]
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if not ctx.get('reconstruction_metrics') or row['status']!='waiting_for_input':raise SystemExit(1)


if __name__=='__main__':main()
