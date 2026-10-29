"""回放已有生成GLB，实际运行CPU检查/修复/导出；不重新建模、调用LLM或写生产任务。"""
import argparse
import json
from pathlib import Path
import shutil
import time
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from image_to_3d_print.api.app import create_app
from image_to_3d_print.artifacts.pbr import source_record
from image_to_3d_print.geometry.commands import dispatch
from image_to_3d_print.geometry.core import MeshStore,load_mesh
from image_to_3d_print.geometry.glb_preserve import GLBDocument,prepare_inspection_glb
from image_to_3d_print.image.assets import AssetStore
from image_to_3d_print.jobs.config import Settings,LLMConfig
from image_to_3d_print.jobs.service import TaskService
from image_to_3d_print.jobs.store import Store
from image_to_3d_print.runtime_contracts import CreateTask
from image_to_3d_print.tools import ToolSession,digest
from image_to_3d_print.workflow.graph import build_graph


def verify(config,source_run,output):
    original_settings=Settings.model_validate_json(config.read_text(encoding='utf-8'))
    source_root=original_settings.root.resolve();output=output.resolve()
    if output.exists() or output==source_root or output.is_relative_to(source_root):
        raise ValueError('必须使用生产存储外尚不存在的独立输出目录')
    old=Store(source_root).row(source_run)['context']
    delivery=old['delivery']
    if old.get('delivery_policy')!='original-glb-v1':raise ValueError('本回放明确要求已登记的历史原始GLB')
    raw=next(a for a in old['artifacts'] if a['artifact_id']==delivery['artifact_id'])
    original=source_root/raw['relative_path'];before=digest(original)
    if before!=delivery['source_sha256']:raise ValueError('历史原始文件摘要不符')
    output.mkdir(parents=True)
    settings=original_settings.model_copy(update={'root':output,'llm':LLMConfig(),'workflow_policy':'automatic_glb'})
    service=TaskService(settings);asset=AssetStore(source_root).get(old['request']['image_asset_id'])
    upload=service.assets.save((source_root/asset.relative_path).read_bytes(),Path(asset.relative_path).name)
    request={**old['request'],'image_asset_id':upload.asset_id,'height_value':100.,'height_unit':'mm',
        'scale_source':'user_target','scale_evidence_id':None,'description':''}
    run=service.create(CreateTask(request=request,backend='trellis2_candidate',export_target_faces=100000))['run_id']
    calls=[]
    def replay(root,command,configuration,**kwargs):
        calls.append(command['operation'])
        if command['operation']!='reconstruct':return dispatch(root,command,configuration,**kwargs)
        session=ToolSession(root,run,'reconstruct');copy=session.directory/'original.glb';shutil.copyfile(original,copy)
        frame=old.get('artifact_frames',{}).get(raw['artifact_id'],'y_up')
        native=session.directory/'raw_mesh.glb';prepare_inspection_glb(copy,native,frame)
        metadata={'official_export_frame':frame,'evidence_origin':'existing_model_replay','source_run':source_run,
            'source_sha256':before,'not_new_inference':True}
        previous=old.get('gpu_boundary_repair')
        if previous:metadata['gpu_boundary_repair']=previous
        version=MeshStore(root).import_mesh(native.relative_to(root).as_posix(),run,
            parameters={'appearance_source':source_record(root,copy,metadata)})
        session.mesh_version=version.mesh_version;session.add('original',copy,'raw_mesh','unitless')
        return session.finish({'mesh_version':version.mesh_version,'model':metadata,
            'evidence_origin':'existing_model_replay','warning':'复用已有真实模型，仅验证其后CPU链，不是本次图片新推理'})
    ctx=service.store.row(run)['context'];ctx.update(status='running',evidence_origin='existing_model_replay')
    start=time.perf_counter()
    with SqliteSaver.from_conn_string(str(output/'checkpoints.sqlite3')) as saver:
        graph=build_graph(settings,service.store,saver,tool_dispatch=replay)
        graph.invoke({'ctx':ctx},{'configurable':{'thread_id':run},'recursion_limit':160})
    row=service.store.row(run);response=row['response'];ctx=row['context']
    (output/'response.json').write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf-8')
    if row['status']!='succeeded':raise RuntimeError(str(ctx.get('error')))
    final_delivery=response['delivery'];final=next(a for a in response['artifacts'] if a['artifact_id']==final_delivery['artifact_id'])
    assert final['kind']=='repaired_mesh'
    assert final['mesh_version']==final_delivery['mesh_version']==response['data']['inspection']['mesh_version']
    assert ctx['repair_attempts']<=2 and calls.count('reconstruct')==1 and 'export_original_glb' not in calls
    source_doc=GLBDocument(original);final_doc=GLBDocument(output/final['relative_path'])
    a=source_doc.material_signature();b=final_doc.material_signature()
    assert a['images_sha256']==b['images_sha256'] and a['textures']==b['textures'] and a['samplers']==b['samplers']
    assert a['materials']==b['materials'][:len(a['materials'])]
    def uv_set(doc):
        return {tuple(uv) for p in doc.primitives if 'TEXCOORD_0' in p['attributes'] for uv in doc.accessor(p['attributes']['TEXCOORD_0'])}
    assert uv_set(final_doc) and uv_set(final_doc)<=uv_set(source_doc)
    mesh=load_mesh(output/final['relative_path']);assert abs(mesh.extents[2]-100)<.01
    assert digest(original)==before
    with TestClient(create_app(settings)) as client:
        result=client.get(f'/api/v1/model-tasks/{run}/artifacts/'+final['artifact_id'])
        assert result.status_code==200 and result.content==(output/final['relative_path']).read_bytes()
    summary={'kind':'existing_model_cpu_replay','source_run':source_run,'run_id':run,'new_model_calls':0,'llm_calls':ctx['llm']['calls'],
        'seconds':time.perf_counter()-start,'source_unchanged':True,'source_sha256':before,'delivery':final_delivery,
        'artifact':final,'appearance':ctx['export_data']['appearance'],'faces':len(mesh.faces),'dimensions_mm':mesh.extents.tolist(),
        'materials_textures_uv_preserved':True,'http_download_matches':True,'calls':calls,'repair_attempt_log':ctx.get('repair_attempt_log',[]),
        'checks':response['data']['inspection']['checks']}
    (output/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ['kind','run_id','seconds','faces','dimensions_mm','new_model_calls','llm_calls','source_unchanged']},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--source-run',required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    verify(args.config,args.source_run,args.output)
