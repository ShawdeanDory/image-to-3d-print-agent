"""本机既有Blender验证质心扇形补洞，不修改原件或调用生产服务。"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
import numpy as np
from image_to_3d_print.geometry.core import load_mesh,topology
from image_to_3d_print.geometry.hole_experiment import centroid_fan_candidate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--blender',type=Path,required=True)
    parser.add_argument('--addon-dir',type=Path,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[2]
    source=args.source.resolve();output=args.output.resolve()
    if output.exists():raise ValueError('输出目录已存在，拒绝覆盖')
    if source.suffix.lower()!='.stl':raise ValueError('本独立试验只接受明确毫米/Z朝上的STL')
    expected=json.loads((root/'locks/linux-geometry-tools.json').read_text())['print_toolbox']['sha256']
    helper=args.addon_dir/'object_print3d_utils/mesh_helpers.py'
    if hashlib.sha256(helper.read_bytes()).hexdigest()!=expected:raise ValueError('检查器版本摘要不符')
    before_hash=hashlib.sha256(source.read_bytes()).hexdigest();original=load_mesh(source)
    candidate,method=centroid_fan_candidate(original)
    output.mkdir(parents=True);records={}
    for name,mesh in [('original',original),('candidate',candidate)]:
        folder=output/name;folder.mkdir();mesh.export(folder/'model.stl')
        payload={'vertices':mesh.vertices.tolist(),'faces':mesh.faces.tolist(),
            'parameters':{'unit':'mm','min_wall_mm':1.2}}
        input_file=folder/'blender-input.json';input_file.write_text(json.dumps(payload),encoding='utf-8')
        argv=[str(args.blender.resolve()),'--background','--factory-startup','--threads','4','--python-exit-code','1',
            '--python',str(root/'scripts/tools/blender_worker.py'),'--','--operation','inspect',
            '--input',str(input_file),'--output',str(folder/'blender-result.json'),'--addon-dir',str(args.addon_dir.resolve())]
        with (folder/'blender.log').open('w',encoding='utf-8') as log:
            run=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        if run.returncode:raise RuntimeError('本机Blender验证失败，保留日志')
        result=json.loads((folder/'blender-result.json').read_text());facts=topology(mesh)
        records[name]={'topology':facts,'self_intersection_faces':len(result['self_intersection_faces']),
            'thin_faces_low':len(result['thin_faces_low']),'thin_faces_high':len(result['thin_faces_high']),
            'overhang_faces':len(result['overhang_faces']),'blender_version':result['blender_version']}
    record=records['candidate'];facts=record['topology']
    passed=(facts['watertight'] and facts['normals_consistent'] and facts['component_count']==1
        and facts['non_manifold_edge_count']==facts['non_manifold_vertex_count']==0
        and record['self_intersection_faces']==record['thin_faces_low']==record['thin_faces_high']==0)
    report={'source_sha256':before_hash,'source_unchanged':before_hash==hashlib.sha256(source.read_bytes()).hexdigest(),
        'platform':'Windows_CPU_Blender_4.5.14','method':method,'records':records,'geometry_gate_passed':passed,
        'production_integrated':False,'print_certified':False,
        'relative_extents_change_percent':float(np.max(abs(candidate.extents-original.extents)/original.extents)*100)}
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'geometry_gate_passed':passed,'records':records,'source_unchanged':report['source_unchanged']}))


if __name__=='__main__':main()
