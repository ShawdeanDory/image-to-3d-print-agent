"""已知几何的真实确认/补洞/组件/简化路径；确认来源明确为测试fixture。"""
import argparse,json,sys,time
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
import trimesh
from image_to_3d_print.geometry.core import MeshStore,load_mesh,topology
from image_to_3d_print.geometry.structure import StructureRequest,propose,confirm,apply_proposal
from image_to_3d_print.inspection.service import InspectionConfig,BedReview,inspect_mesh
from image_to_3d_print.artifacts.export import export_mesh
from image_to_3d_print.schemas import PrinterProfile
from image_to_3d_print.tools import ToolFailure

def main():
    p=argparse.ArgumentParser();p.add_argument('--cloud-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    config=InspectionConfig(blender=args.cloud_root/'runtime/tools/blender-4.5.14-linux-x64/blender',addon_dir=args.cloud_root/'runtime/upstream/blender-addons')
    profile=PrinterProfile.model_validate_json((ROOT/'fixtures/p1/printer_profile.json').read_text());store=MeshStore(ROOT);records=[]
    for name,request in [('open_cube.obj',StructureRequest(operation='fill_small_holes')),
        ('multiple_components.obj',StructureRequest(operation='remove_components',remove_components=[1]))]:
        run=uuid4();source=store.import_mesh('fixtures/p1/geometry/'+name,run,'mm')
        proposal=propose(ROOT,run,source.mesh_version,request)
        unconfirmed=apply_proposal(ROOT,run,proposal.proposal_id)
        assert not unconfirmed.tool.succeeded
        confirm(ROOT,run,proposal.proposal_id,'known_fixture_runner',True,origin='test_fixture')
        result=apply_proposal(ROOT,run,proposal.proposal_id);assert result.tool.succeeded
        version=result.tool.data['mesh_version']
        inspection=inspect_mesh(ROOT,run,version,profile,height_mm=10.,bed_review=BedReview(mesh_version=version,confirmed=True,reviewer='known_fixture_runner',origin='test_fixture'),config=config)
        inspection_data=inspection.tool.data['inspection'];assert inspection_data['watertight'] and inspection_data['normals_consistent']
        export=export_mesh(ROOT,run,version);assert export.tool.succeeded
        records.append({'case':name,'proposal':proposal.model_dump(mode='json'),'unconfirmed_blocked':True,'applied':result.model_dump(mode='json'),
            'inspection':inspection.model_dump(mode='json'),'export':export.model_dump(mode='json')})
        (args.output/'partial.json').write_text(json.dumps({'records':records,'complete':False},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    run=uuid4();source_file=args.output/'large_sphere.ply'
    sphere=trimesh.creation.icosphere(subdivisions=7,radius=20.);sphere.apply_translation([0,0,20]);sphere.export(source_file)
    source=store.import_mesh(source_file.relative_to(ROOT).as_posix(),run,'mm')
    try:
        proposal=propose(ROOT,run,source.mesh_version,StructureRequest(operation='simplify',target_faces=80000),config)
        confirm(ROOT,run,proposal.proposal_id,'known_fixture_runner',True,origin='test_fixture')
        result=apply_proposal(ROOT,run,proposal.proposal_id);assert result.tool.succeeded
        records.append({'case':'known_large_sphere','proposal':proposal.model_dump(mode='json'),'applied':result.model_dump(mode='json')})
    except ToolFailure as exc:records.append({'case':'known_large_sphere','error':{'code':exc.code,'message':str(exc)}})
    report={'kind':'real_structural_tool_fixtures','records':records,'seconds':time.perf_counter()-started,
        'confirmation_origin':'test_fixture','human_acceptance':False,'gpu_used':False}
    (args.output/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'cases':len(records),'errors':[r['error'] for r in records if 'error' in r],'seconds':report['seconds']}))
    return any('error' in r for r in records)

if __name__=='__main__':raise SystemExit(main())
