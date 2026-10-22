"""复用已有开发网格验证图片预算和真实CPUBlender；不重建、不调用LLM。"""
import argparse,json,hashlib,time,shutil
from pathlib import Path
from uuid import uuid4
from langgraph.checkpoint.sqlite import SqliteSaver
from image_to_3d_print.jobs.config import Settings
from image_to_3d_print.jobs.service import TaskService
from image_to_3d_print.runtime_contracts import CreateTask
from image_to_3d_print.geometry.core import MeshStore,load_mesh,topology
from image_to_3d_print.geometry.commands import dispatch
from image_to_3d_print.workflow.graph import build_graph
from image_to_3d_print.workflow.state import save_context
from image_to_3d_print.schemas.task import ModelTaskRequest
from image_to_3d_print.tools import ToolSession


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--source-run',default='9e10c058-029e-47d3-991b-d6b44718e73d');args=parser.parse_args()
    p=args.project;folder=p/'runs/adaptive-mesh-20261022-01';folder.mkdir(exist_ok=True)
    original=Settings.model_validate_json((p/'runtime/config/backend.json').read_text());production=TaskService(original)
    old=production.store.row(args.source_run)['context'];source=MeshStore(original.root).get(args.source_run,old['mesh_version'])
    if source.unit!='mm':raise ValueError('需要已有毫米开发网格')
    settings=original.model_copy(update={'root':folder/'application','workflow_policy':'automatic_glb','llm':type(original.llm)()})
    (folder/'config.json').write_text(settings.model_dump_json(indent=2)+'\n');service=TaskService(settings)
    asset=production.assets.get(old['request']['image_asset_id']);content=(original.root/asset.relative_path).read_bytes()
    image=service.assets.save(content,'duck.jpg');(folder/'duck.jpg').write_bytes(content)
    req=ModelTaskRequest.model_validate({**old['request'],'image_asset_id':image.asset_id,'description':'','orientation':{'up_axis':'z','confirmed':False}})
    created=service.create(CreateTask(request=req,backend=old['backend']));run=created['run_id'];(folder/'run-id.txt').write_text(run)
    raw=settings.root/'existing-mm-mesh.ply';shutil.copy2(original.root/source.relative_path,raw)
    version=MeshStore(settings.root).import_mesh(raw.name,run,'mm',{'validation_source_run':args.source_run,'source_sha256':source.sha256})
    ctx=service.store.row(run)['context'];ctx.update(status='running',stage='inspect',next='inspect',mesh_version=version.mesh_version,
        evidence_origin='existing_real_mesh_replay',validation_source_run=args.source_run,reconstruction_skipped=True)
    outcome=dispatch(settings.root,{'run_id':run,'operation':'analyze_complexity','asset_id':image.asset_id},settings.tools)
    if not outcome.tool.succeeded:raise ValueError('复杂度工具失败')
    ctx['mesh_budget']=outcome.tool.data['analysis'];ctx['tool_calls']=1
    ctx['artifacts']=[a.model_dump(mode='json') for a in outcome.artifacts];ctx['evidence']=[e.model_dump(mode='json') for e in outcome.evidence]
    original_artifact=ToolSession(settings.root,run,'preprocess',version.mesh_version).add('existing_source',settings.root/version.relative_path,'raw_mesh','mm')
    ctx['artifacts'].append(original_artifact.model_dump(mode='json'))
    ctx['operations']=[{'operation':'analyze_complexity','origin':'automatic_policy','result':outcome.tool.model_dump(mode='json')}]
    save_context(service.store,ctx,'validation_existing_mesh',{'new_reconstruction':False,'llm_calls':0})
    started=time.perf_counter()
    with SqliteSaver.from_conn_string(str(service.store.root/'checkpoints.sqlite3')) as saver:
        graph=build_graph(settings,service.store,saver);configuration={'configurable':{'thread_id':run},'recursion_limit':160}
        graph.update_state(configuration,{'ctx':ctx},as_node='scale');graph.invoke(None,configuration)
    row=service.store.row(run);ctx=row['context'];record=MeshStore(settings.root).get(run,ctx['mesh_version']);mesh=load_mesh(settings.root/record.relative_path)
    result={'validation_mode':'existing_real_mesh_replay','run_id':run,'source_run':args.source_run,'new_reconstruction':False,
        'source_sha256':source.sha256,'source_unchanged':hashlib.sha256((original.root/source.relative_path).read_bytes()).hexdigest()==source.sha256,
        'seconds':time.perf_counter()-started,'status':row['status'],'mesh_budget':ctx.get('mesh_budget'),
        'repair_attempt_log':ctx.get('repair_attempt_log',[]),'delivery':ctx.get('delivery'),
        'geometry':topology(mesh),'inspection':ctx.get('inspection'),'operations':[o['operation'] for o in ctx['operations']],
        'llm_calls':ctx['llm']['calls'],'proposals':[]}
    for file in (service.store.root/'runs'/run/'proposals').glob('*/proposal.json'):
        proposal=json.loads(file.read_text());result['proposals'].append({'request':proposal['request'],'changes':proposal['changes']})
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['run_id','status','seconds','mesh_budget','repair_attempt_log','source_unchanged']},ensure_ascii=False))
    assert row['status']=='succeeded' and result['source_unchanged'] and ctx['llm']['calls']==0


if __name__=='__main__':main()
