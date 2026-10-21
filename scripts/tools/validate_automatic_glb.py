"""同实例真实开发验证准备/收集；不含模型替身，不发起人工确认。"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from image_to_3d_print.jobs.config import Settings
from image_to_3d_print.jobs.service import TaskService
from image_to_3d_print.geometry.core import MeshStore,load_mesh,topology
from image_to_3d_print.runtime_contracts import GenerationTaskResponse


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--run');args=parser.parse_args();project=args.project.resolve()
    folder=project/'runs/automatic-glb-20261021-01';folder.mkdir(exist_ok=True)
    path=folder/'config.json'
    if not args.run:
        original=json.loads((project/'runtime/config/backend.json').read_text())
        production=TaskService(Settings.model_validate(original));asset=production.assets.get('a_f727e3f9b1a24d999c4e38d616ce5cf8')
        content=(production.store.root/asset.relative_path).read_bytes()
        assert hashlib.sha256(content).hexdigest()=='1d6ac093c18648fc9568f58e310db3d1666d942cb0a2ea36b21be8384993f4ff'
        (folder/'duck.jpg').write_bytes(content)
        config={**original,'root':str(folder/'application'),'workflow_policy':'automatic_glb',
            'default_backend':'trellis2_candidate','llm':{},'confirmation_origin':'test_fixture'}
        path.write_text(json.dumps(config,indent=2)+'\n')
        TaskService(Settings.model_validate(config))
        print(json.dumps({'kind':'real_validation_prepared','workflow_policy':'automatic_glb','input_sha256':hashlib.sha256(content).hexdigest(),'llm_calls_enabled':False}));return
    service=TaskService(Settings.model_validate_json(path.read_text()));row=service.store.row(args.run);ctx=row['context']
    response=GenerationTaskResponse.model_validate(row['response']);delivery=response.delivery
    assert row['status']=='succeeded' and delivery and ctx['pending'] is None
    assert not ctx.get('human_reviews') and not ctx.get('slicer_confirmation')
    assert len([o for o in ctx['operations'] if o['operation']=='reconstruct'])==1
    assert ctx.get('repair_attempts',0)<=2
    with service.store.connect() as db:submissions=db.execute('SELECT COUNT(*) FROM submissions WHERE run=?',(args.run,)).fetchone()[0]
    assert submissions==0
    artifact=next(a for a in response.artifacts if a.artifact_id==delivery.artifact_id)
    mesh=load_mesh(service.store.root/artifact.relative_path)
    result={'run_id':args.run,'status':row['status'],'response_schema':response.schema_version,
        'workflow_policy':ctx['workflow_policy'],'input_sha256':hashlib.sha256((folder/'duck.jpg').read_bytes()).hexdigest(),
        'active_seconds':row['active_seconds'],'delivery':delivery.model_dump(mode='json'),
        'pending':ctx['pending'],'human_reviews':ctx.get('human_reviews',[]),'submitted_confirmations':submissions,
        'repair_log':ctx.get('repair_attempt_log',[]),'operations':[o['operation'] for o in ctx['operations']],
        'model':ctx.get('reconstruction_metrics'),'geometry':topology(mesh),'visual_kind':mesh.visual.kind,
        'color_range':np.ptp(mesh.visual.vertex_colors[:,:3].astype(int),axis=0).tolist() if mesh.visual.kind=='vertex' else None,
        'inspection':ctx.get('inspection'),'llm_calls':ctx['llm']['calls'],'independent_glb_bytes':(service.store.root/artifact.relative_path).stat().st_size}
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
