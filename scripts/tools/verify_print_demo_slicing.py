"""明确在本机复用P0的PrusaSlicer2.9.6；不向打印机发送命令。"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import numpy as np
from image_to_3d_print.tools import ToolOutcome,digest
from image_to_3d_print.geometry.core import load_mesh
from image_to_3d_print.print_demo import gcode_summary


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--attempt',default='slicing');args=parser.parse_args()
    if not re.fullmatch(r'[a-z0-9_-]{1,32}',args.attempt):raise ValueError('切片记录名称无效')
    repo=Path(__file__).resolve().parents[2];root=args.root.resolve()
    result=ToolOutcome.model_validate_json((root/'result.json').read_text(encoding='utf-8'));data=result.tool.data
    if not result.tool.succeeded or not data['ready_for_slicing']:raise ValueError('几何尚未达到切片门槛')
    artifact=next(a for a in result.artifacts if a.kind=='candidate_stl' and a.mesh_version==data['mesh_version'])
    source=(root/artifact.relative_path).resolve()
    if not source.is_relative_to(root):raise ValueError('STL越出本次交付目录')
    independent=load_mesh(source)
    if not np.allclose(independent.extents,data['dimensions_mm'],atol=.01):raise ValueError('STL尺寸与实际检查版本不符')
    exe=repo/'runtime/tools/prusaslicer/PrusaSlicer-2.9.6/prusa-slicer-console.exe'
    if not exe.is_file():raise ValueError('本机尚无已验证的PrusaSlicer2.9.6，不静默换切片机')
    version=subprocess.run([str(exe),'--help'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
    if '2.9.6' not in version.stdout+version.stderr:raise ValueError('实际切片器版本不符')
    output=root/args.attempt
    output.mkdir(exist_ok=False);gcode=output/'demo-only-not-printer-specific.gcode';profile=repo/'fixtures/print_demo/demo_fdm_pla_supports.ini'
    command=[str(exe),'--datadir',str(output/'datadir'),'--load',str(profile),'--config-compatibility','disable',
        '--export-gcode','--center','110,110','--output',str(gcode),str(source)]
    started=time.perf_counter()
    with (output/'slicer.log').open('w',encoding='utf-8') as log:
        try:process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=180);code=process.returncode
        except subprocess.TimeoutExpired:code=124
    summary={'slicer':'PrusaSlicer2.9.6','execution_machine':'local_windows','run_id':str(result.tool.run_id),
        'mesh_version':data['mesh_version'],'stl_sha256':digest(source),'profile_sha256':digest(profile),'profile_kind':'demo',
        'returncode':code,'seconds':time.perf_counter()-started,'supports_enabled':True,'physical_print':False,'passed':False}
    if code==0 and gcode.is_file():
        content=gcode.read_text(encoding='utf-8');summary.update(gcode_summary(content,data['dimensions_mm'][2],.2,supports=True))
        summary.update(gcode_bytes=gcode.stat().st_size,gcode_sha256=digest(gcode),
            material_estimate=[line for line in content.splitlines() if re.match(r'; (filament used|estimated printing time)',line)])
    (output/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
    if not summary['passed']:raise SystemExit(2)


if __name__=='__main__':main()
