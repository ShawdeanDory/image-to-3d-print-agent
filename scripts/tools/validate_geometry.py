"""Linux真实打印检查器fixture验证，与离线替身测试分开。"""
import argparse,json,os,sys,time
from pathlib import Path
from uuid import uuid4
os.environ['CUDA_VISIBLE_DEVICES']=''
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from image_to_3d_print.geometry.core import MeshStore
from image_to_3d_print.inspection.service import InspectionConfig,BedReview,inspect_mesh
from image_to_3d_print.schemas import PrinterProfile
from image_to_3d_print.tools import new_directory

def main():
    p=argparse.ArgumentParser();p.add_argument('--cloud-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    config=InspectionConfig(blender=args.cloud_root/'runtime/tools/blender-4.5.14-linux-x64/blender',addon_dir=args.cloud_root/'runtime/upstream/blender-addons')
    profile=PrinterProfile.model_validate_json((ROOT/'fixtures/p1/printer_profile.json').read_text())
    store=MeshStore(ROOT);results=[];started=time.perf_counter()
    fixtures=json.loads((ROOT/'fixtures/p1/geometry/manifest.json').read_text())['fixtures']
    for fixture in fixtures:
        name=fixture['file'];run=uuid4()
        version=store.import_mesh('fixtures/p1/geometry/'+name,run,'mm')
        result=inspect_mesh(ROOT,run,version.mesh_version,profile,height_mm=10 if name in {'cube_10mm.stl','multiple_components.obj'} else None,
            bed_review=BedReview(mesh_version=version.mesh_version,confirmed=True,reviewer='known_fixture_runner',origin='test_fixture'),config=config)
        checks={c['name']:c for c in result.tool.data.get('inspection',{}).get('checks',[])}
        results.append({'fixture':name,'tool_succeeded':result.tool.succeeded,'error':result.tool.error.model_dump() if result.tool.error else None,
            'checks':checks,'inspection':result.tool.data.get('inspection'),'verdict':result.tool.data.get('verdict'),
            'outcome_path':next(a.relative_path for a in result.artifacts if a.artifact_id.endswith('_report'))})
    byname={r['fixture']:r for r in results}
    expected=[('cube_10mm.stl','watertight','pass'),('cube_10mm.stl','self_intersection','pass'),('cube_10mm.stl','wall_thickness','pass'),
        ('open_cube.obj','boundary_edges','fail'),('reversed_face.obj','normals','fail'),('duplicate_face.obj','non_manifold_edges','fail'),
        ('non_manifold_vertex.obj','non_manifold_vertices','fail'),('self_intersection.stl','self_intersection','fail'),
        ('thin_wall_0p9mm.stl','wall_thickness','fail'),('thin_wall_0p6mm.obj','wall_thickness','fail'),
        ('thin_wall_1p2mm.obj','wall_thickness','warn'),('wall_1p6mm.obj','wall_thickness','pass'),('slanted_face.obj','overhang','warn'),
        ('multiple_components.obj','components','warn')]
    mismatches=[{'fixture':name,'check':check,'expected':expect,'actual':byname[name]['checks'].get(check,{}).get('status')} for name,check,expect in expected if byname[name]['checks'].get(check,{}).get('status')!=expect]
    report={'kind':'real_linux_geometry_fixtures','fixtures':results,'expectations':len(expected),'mismatches':mismatches,'seconds':time.perf_counter()-started,'gpu_used':False,'synthetic_confirmations':'test_fixture_only'}
    (args.output/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'fixtures':len(results),'mismatches':mismatches,'seconds':report['seconds']}))
    return bool(mismatches) or not all(r['tool_succeeded'] for r in results)

if __name__=='__main__':raise SystemExit(main())
