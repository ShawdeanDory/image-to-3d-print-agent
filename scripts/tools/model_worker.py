"""在锁定后端环境内工作，不导入服务层，不联网，不选官方固定图。"""
import argparse,importlib.util,json,os,runpy,shutil,hashlib
from pathlib import Path
import sys,time,subprocess
from contextlib import nullcontext

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['reconstruct','background'],required=True)
    parser.add_argument('--backend',choices=['triposr','trellis2_candidate'],required=True)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--seed',type=int,default=None)
    parser.add_argument('--profile',choices=['official','course_fast','legacy_geometry'],default='official')
    parser.add_argument('--export-target-faces',type=int,default=None)
    parser.add_argument('--texture-size',type=int,default=None)
    parser.add_argument('--gpu-hole-repair',action='store_true')
    args=parser.parse_args()
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
    if args.export_target_faces is not None and not 100<=args.export_target_faces<=1000000:
        parser.error('export-target-faces必须在100～1000000之间')
    if args.texture_size is not None and not 256<=args.texture_size<=4096:
        parser.error('texture-size必须在256～4096之间')
    if (args.export_target_faces is not None or args.texture_size is not None) and (args.profile!='course_fast' or args.backend!='trellis2_candidate'):
        parser.error('手动导出参数仅支持TRELLIS.2快速入口')
    import numpy as np
    import torch
    import trimesh
    from PIL import Image,ImageOps
    if not torch.cuda.is_available():raise RuntimeError('cuda_unavailable')
    torch.set_num_threads(4)
    if args.profile=='legacy_geometry' or args.mode=='background':torch.manual_seed(args.seed or 0)
    torch.cuda.reset_peak_memory_stats()
    started=time.perf_counter()
    with Image.open(args.input) as original:image=ImageOps.exif_transpose(original).convert('RGBA' if args.mode=='reconstruct' else 'RGB')
    source=args.root/'runtime/upstream'/('TripoSR' if args.backend=='triposr' else 'TRELLIS.2')
    sys.path.insert(0,str(source))
    if args.mode=='reconstruct' and args.profile=='course_fast':
        if args.backend!='trellis2_candidate':raise ValueError('course_fast_requires_trellis2')
        course_fast_inference(args,source,torch,started)
        return
    if args.mode=='reconstruct' and args.profile=='official':
        official_inference(args,source,torch,started)
        return
    if args.mode=='background':
        from huggingface_hub import snapshot_download
        filename=source/'trellis2/pipelines/rembg/BiRefNet.py'
        spec=importlib.util.spec_from_file_location('fixed_rembg',filename);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        snapshot=snapshot_download('briaai/RMBG-2.0',revision='5df4c9c76d8170882c34f6986e848ee07fd0ba43',local_files_only=True)
        model=module.BiRefNet(snapshot);model.cuda();torch.cuda.synchronize();loaded=time.perf_counter()
        model(image).save(args.output/'background_removed.png');torch.cuda.synchronize();inferred=time.perf_counter()
        parameters={'repo':'briaai/RMBG-2.0','revision':'5df4c9c76d8170882c34f6986e848ee07fd0ba43','official_wrapper':'BiRefNet'}
    elif args.backend=='triposr':
        from tsr.system import TSR
        from tsr.utils import resize_foreground
        model=TSR.from_pretrained(str(args.root/'weights/TripoSR'),config_name='config.yaml',weight_name='model.ckpt')
        model.renderer.set_chunk_size(2048);model.eval().to('cuda:0');torch.cuda.synchronize();loaded=time.perf_counter()
        image=resize_foreground(image,.85);rgba=np.array(image).astype(np.float32)/255
        rgb=rgba[:,:,:3]*rgba[:,:,3:]+(1-rgba[:,:,3:])*.5
        image=Image.fromarray((rgb*255).astype(np.uint8));image.save(args.output/'backend_input.png')
        with torch.inference_mode():
            codes=model([image],device='cuda:0');torch.cuda.synchronize();inferred=time.perf_counter()
            mesh=model.extract_mesh(codes,has_vertex_color=False,resolution=128)[0]
        from image_to_3d_print.geometry.glb_preserve import write_plain_glb
        write_plain_glb(mesh,args.output/'raw_mesh.glb','unitless')
        parameters={'mc_resolution':128,'chunk_size':2048,'foreground_ratio':.85,'background':'gray','coordinates':'native_z_up'}
    else:
        from trellis2.pipelines import Trellis2ImageTo3DPipeline
        model=Trellis2ImageTo3DPipeline.from_pretrained('microsoft/TRELLIS.2-4B');model.cuda()
        torch.cuda.synchronize();loaded=time.perf_counter()
        prepared=model.preprocess_image(image);prepared.save(args.output/'backend_input.png')
        with torch.inference_mode():
            output=model.run(prepared,seed=args.seed or 0,preprocess_image=False,pipeline_type='1024_cascade')[0]
        torch.cuda.synchronize();inferred=time.perf_counter()
        mesh=trimesh.Trimesh(vertices=output.vertices.detach().cpu().numpy(),faces=output.faces.detach().cpu().numpy(),process=False)
        from image_to_3d_print.geometry.glb_preserve import write_plain_glb
        write_plain_glb(mesh,args.output/'raw_mesh.glb','unitless')
        parameters={'pipeline_type':'1024_cascade','preprocessing':'official_alpha_crop_black_composite','coordinates':'native_z_up_no_glb_axis_conversion',
            'upstream_internal_processing':'pipeline decoding unchanged; no PBR video or postprocess.to_glb'}
    torch.cuda.synchronize()
    report={'mode':args.mode,'backend':args.backend,'seed':args.seed or 0,'parameters':parameters,'torch':torch.__version__,
        'cuda_runtime':torch.version.cuda,'device':torch.cuda.get_device_name(0),'input_file':args.input.name,
        'seconds':{'load_and_prepare':loaded-started,'inference':inferred-loaded,'total':time.perf_counter()-started},
        'timing_scope':'inference includes backend image processing and model decoding; process startup is separately recorded',
        'peak_allocated_mib':torch.cuda.max_memory_allocated()/2**20,'peak_reserved_mib':torch.cuda.max_memory_reserved()/2**20}
    (args.output/'model.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

def official_inference(args,source,torch,started):
    from PIL import Image
    import trimesh
    # 只引入纯读回模块，不把服务端依赖混入已通过模型环境。
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
    from image_to_3d_print.adapters.official import read_official_geometry
    output=args.output.resolve();directory=output/'official';directory.mkdir(exist_ok=False)
    previous_cwd=Path.cwd();previous_argv=sys.argv[:];restore_extract=None;gpu_reports=[]
    try:
        if args.backend=='triposr':
            if args.gpu_hole_repair:
                from tsr.system import TSR
                restore_extract=TSR.extract_mesh
                def gpu_extract(model,*a,**k):
                    meshes=restore_extract(model,*a,**k)
                    for i,mesh in enumerate(meshes):
                        original=output/f'before_gpu_repair_{i}.ply';candidate=output/f'gpu_candidate_{i}.ply';report_file=output/f'gpu_repair_{i}.json'
                        mesh.export(original)
                        environment=args.root/'runtime/envs/trellis2/bin/python'
                        try:
                            if not environment.is_file():raise FileNotFoundError('gpu_repair_environment_missing')
                            subprocess.run([str(environment),str(Path(__file__).with_name('gpu_hole_worker.py')),
                                '--input',str(original),'--output',str(candidate),'--report',str(report_file)],check=True)
                            gpu_reports.append(json.loads(report_file.read_text(encoding='utf-8')))
                            meshes[i]=trimesh.load(candidate,force='mesh',process=False)
                        except (subprocess.CalledProcessError,OSError,ValueError) as exc:
                            from image_to_3d_print.geometry.gpu_holes import failed_gpu_report
                            gpu_reports.append(failed_gpu_report(exc))
                    return meshes
                TSR.extract_mesh=gpu_extract
            if not (Path(os.environ.get('U2NET_HOME',''))/'u2net.onnx').is_file():
                raise RuntimeError('official_u2net_missing:先准备官方rembg权重，运行期间不自动联网')
            entry=source/'run.py'
            sys.argv=[str(entry),str(args.input.resolve()),'--pretrained-model-name-or-path',str(args.root/'weights/TripoSR'),
                '--output-dir',str(directory),'--model-save-format','glb']
            os.chdir(source)
            result=runpy.run_path(str(entry),run_name='__main__')
            exported=directory/'0/mesh.glb';frame='z_up'
            options=result['args']
            parameters={name:getattr(options,name) for name in ['mc_resolution','chunk_size','foreground_ratio','bake_texture','texture_resolution']}
            seed=None
        else:
            entry=source/'example.py'
            inputs=directory/'assets/example_image';inputs.mkdir(parents=True)
            hdri=directory/'assets/hdri';hdri.mkdir()
            # 未改官方脚本；隔离工作目录中的T.png是本次用户图片的逐字节副本。
            shutil.copyfile(args.input,inputs/'T.png')
            shutil.copyfile(source/'assets/hdri/forest.exr',hdri/'forest.exr')
            assert hashlib.sha256((inputs/'T.png').read_bytes()).digest()==hashlib.sha256(args.input.read_bytes()).digest()
            sys.argv=[str(entry)];os.chdir(directory)
            result=runpy.run_path(str(entry),run_name='__main__')
            native=result['mesh']
            trimesh.Trimesh(vertices=native.vertices.detach().cpu().numpy(),faces=native.faces.detach().cpu().numpy(),process=False).export(output/'native_mesh.ply')
            exported=directory/'sample.glb';frame='y_up'
            parameters={'pipeline_type':'1024_cascade','seed':42,'decimation_target':1000000,'texture_size':4096,
                'remesh':True,'remesh_band':1,'remesh_project':0,'official_pbr_video':True}
            seed=42
        torch.cuda.synchronize()
        if gpu_reports:
            (output/'gpu_repair.json').write_text(json.dumps(gpu_reports,indent=2)+'\n',encoding='utf-8')
            if (output/'before_gpu_repair_0.ply').is_file():shutil.copyfile(output/'before_gpu_repair_0.ply',output/'before_gpu_repair.ply')
        shutil.copyfile(exported,output/'official_export.glb')
        from image_to_3d_print.geometry.glb_preserve import prepare_inspection_glb
        prepare_inspection_glb(output/'official_export.glb',output/'raw_mesh.glb',frame)
        with Image.open(args.input) as image:dimensions=list(image.size)
        report={'mode':args.mode,'backend':args.backend,'inference_profile':'official','seed':seed,'parameters':parameters,
            'official_entry':entry.name,'official_entry_sha256':hashlib.sha256(entry.read_bytes()).hexdigest(),
            'official_export_frame':frame,'geometry_frame':'z_up','geometry_source':'official_export_readback',
            'input_dimensions':dimensions,'additional_downsampling':False,'torch':torch.__version__,
            'gpu_boundary_repair':gpu_reports[0] if len(gpu_reports)==1 else None,
            'post_extraction_gpu_variant':bool(gpu_reports),
            'cuda_runtime':torch.version.cuda,'device':torch.cuda.get_device_name(0),'input_file':args.input.name,
            'seconds':{'load_and_prepare':None,'inference':None,'total':time.perf_counter()-started},
            'timing_scope':'official entry plus explicit optional GPU geometry variant and independent readback; model-only time not instrumented',
            'peak_allocated_mib':torch.cuda.max_memory_allocated()/2**20,'peak_reserved_mib':torch.cuda.max_memory_reserved()/2**20}
        (output/'model.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report))
    finally:
        if restore_extract is not None:
            from tsr.system import TSR
            TSR.extract_mesh=restore_extract
        os.chdir(previous_cwd);sys.argv=previous_argv

def course_fast_inference(args,source,torch,started):
    """同一官方库/权重的显式工程变体；不伪称未改example.py。"""
    from PIL import Image,ImageOps
    import trimesh
    from trellis2.pipelines import Trellis2ImageTo3DPipeline
    from o_voxel import postprocess
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
    from image_to_3d_print.adapters.official import read_official_geometry
    output=args.output.resolve();stages={}
    target_faces=args.export_target_faces if args.export_target_faces is not None else 100000
    texture_size=args.texture_size if args.texture_size is not None else 2048
    def stamp():
        torch.cuda.synchronize()
        return time.perf_counter()
    pipeline=Trellis2ImageTo3DPipeline.from_pretrained('microsoft/TRELLIS.2-4B');pipeline.cuda()
    loaded=stamp();stages['load_and_prepare']=loaded-started
    with Image.open(args.input) as original:
        dimensions=list(original.size);image=ImageOps.exif_transpose(original).copy()
    prepared=pipeline.preprocess_image(image);prepared.save(output/'backend_input.png')
    ready=stamp();stages['preprocess']=ready-loaded
    with torch.inference_mode():
        native=pipeline.run(prepared,seed=42,preprocess_image=False,pipeline_type='1024_cascade')[0]
        native.simplify(16777216)
    inferred=stamp();stages['inference']=inferred-ready
    trimesh.Trimesh(vertices=native.vertices.detach().cpu().numpy(),faces=native.faces.detach().cpu().numpy(),process=False).export(output/'native_mesh.ply')
    native_written=stamp();stages['native_export']=native_written-inferred
    from image_to_3d_print.geometry.gpu_holes import before_pbr_export
    gpu_reports=[];snapshots=[]
    with before_pbr_export(gpu_reports,snapshots) if args.gpu_hole_repair else nullcontext():
        glb=postprocess.to_glb(vertices=native.vertices,faces=native.faces,attr_volume=native.attrs,
            coords=native.coords,attr_layout=native.layout,voxel_size=native.voxel_size,
            aabb=[[-.5,-.5,-.5],[.5,.5,.5]],decimation_target=target_faces,texture_size=texture_size,
            remesh=True,remesh_band=1,remesh_project=0,verbose=True)
    for vertices,faces in snapshots:
        trimesh.Trimesh(vertices.detach().cpu().numpy(),faces.detach().cpu().numpy(),process=False).export(output/'before_gpu_repair.ply')
    (output/'gpu_repair.json').write_text(json.dumps(gpu_reports,indent=2)+'\n',encoding='utf-8')
    glb.export(output/'fast_export.glb')
    exported=stamp();stages['geometry_uv_texture_export']=exported-native_written
    from image_to_3d_print.geometry.glb_preserve import prepare_inspection_glb
    geometry=prepare_inspection_glb(output/'fast_export.glb',output/'raw_mesh.glb','y_up')
    finished=stamp();stages['independent_readback']=finished-exported;stages['total']=finished-started
    parameters={'pipeline_type':'1024_cascade','seed':42,'decimation_target':target_faces,'texture_size':texture_size,
        'export_target_source':'task_budget' if args.export_target_faces is not None else 'automatic_generation_ceiling',
        'texture_size_source':'manual' if args.texture_size is not None else 'default',
        'remesh':True,'remesh_band':1,'remesh_project':0,'official_pbr_video':False}
    report={'mode':args.mode,'backend':args.backend,'inference_profile':'course_fast','seed':42,'parameters':parameters,
        'official_entry':None,'upstream_library':'trellis2.pipelines + o_voxel.postprocess.to_glb',
        'official_export_frame':'y_up','geometry_frame':'z_up','geometry_source':'fast_export_readback',
        'appearance':{'original':'pbr_glb','processed':'original_uv_pbr_preserved'},
        'input_dimensions':dimensions,'additional_downsampling':False,'torch':torch.__version__,
        'cuda_runtime':torch.version.cuda,'device':torch.cuda.get_device_name(0),'input_file':args.input.name,
        'seconds':stages,'face_count':geometry['face_count'],'vertex_count':geometry['vertex_count'],
        'gpu_boundary_repair':gpu_reports[0] if len(gpu_reports)==1 else None,
        'timing_scope':'CUDA synchronized, disjoint stages; UV/remesh/baking combined inside upstream to_glb; no video; process startup separately recorded',
        'peak_allocated_mib':torch.cuda.max_memory_allocated()/2**20,'peak_reserved_mib':torch.cuda.max_memory_reserved()/2**20}
    (output/'model.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report))


if __name__=='__main__':main()
