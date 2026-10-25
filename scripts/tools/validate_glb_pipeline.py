"""已有原GLB的CPU清理/定标/真实打印检查，不运行重建或LLM。"""
import argparse,json,pathlib,sys
from uuid import uuid4
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'src'))
from image_to_3d_print.geometry.glb_preserve import GLBDocument,prepare_inspection_glb
from image_to_3d_print.geometry.core import MeshStore,load_mesh
from image_to_3d_print.schemas import ModelTaskRequest,PrinterProfile
from image_to_3d_print.inspection.service import InspectionConfig,inspect_mesh
from image_to_3d_print.artifacts.export import export_preview
from image_to_3d_print.tools import digest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=pathlib.Path,required=True)
    p.add_argument('--source',type=pathlib.Path,required=True);p.add_argument('--config',type=pathlib.Path,required=True)
    args=p.parse_args();args.root.mkdir(parents=True,exist_ok=False)
    before=digest(args.source);prepare_inspection_glb(args.source,args.root/'input.glb','y_up')
    store=MeshStore(args.root);run=uuid4();raw=store.import_mesh('input.glb',run)
    clean=store.clean(run,raw.mesh_version,count_repair_round=False)
    if not clean.tool.succeeded:raise RuntimeError(clean.tool.error)
    request=ModelTaskRequest(image_asset_id='existing-source',printer_profile_id='demo_v1',height_value=100.,height_unit='mm',scale_source='user_target',orientation={'up_axis':'z','confirmed':True})
    scaled=store.scale(run,clean.tool.data['mesh_version'],request)
    if not scaled.tool.succeeded:raise RuntimeError(scaled.tool.error)
    final=store.get(run,scaled.tool.data['mesh_version']);file=args.root/final.relative_path
    if GLBDocument(file).material_signature()!=GLBDocument(args.source).material_signature():raise ValueError('材质未保持')
    config=json.loads(args.config.read_text());inspection=InspectionConfig.model_validate(config.get('tools',{}).get('inspection',config.get('inspection')))
    profile=PrinterProfile.model_validate_json((pathlib.Path(__file__).resolve().parents[2]/'fixtures/p1/printer_profile.json').read_text())
    result=inspect_mesh(args.root,run,final.mesh_version,profile,height_mm=100.,config=inspection,automatic_bed=True)
    if not result.tool.succeeded:raise RuntimeError(result.tool.error)
    exported=export_preview(args.root,run,final.mesh_version)
    if not exported.tool.succeeded:raise RuntimeError(exported.tool.error)
    if list(args.root.rglob('*.ply')):raise ValueError('检查链仍生成PLY')
    if digest(args.source)!=before:raise ValueError('源文件被修改')
    report={'source_unchanged':True,'model_runs':0,'llm_calls':0,'rebakes':0,'source_faces':len(load_mesh(args.root/raw.relative_path).faces),
        'final_faces':len(load_mesh(file).faces),'inspection_file_type':'.glb','intermediate_ply_files':0,
        'uv_material_texture_preserved':True,'logical_dimensions_mm':load_mesh(file).extents.tolist(),
        'blender_inspection_executed':True,'print_verdict':result.tool.data.get('verdict'),'export_appearance':exported.tool.data['appearance']}
    (args.root/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
