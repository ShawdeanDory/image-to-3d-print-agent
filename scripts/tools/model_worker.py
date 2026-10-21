"""在锁定后端环境内工作，不导入服务层，不联网，不选官方固定图。"""
import argparse,importlib.util,json,os
from pathlib import Path
import sys,time

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['reconstruct','background'],required=True)
    parser.add_argument('--backend',choices=['triposr','trellis2_candidate'],required=True)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--seed',type=int,default=0)
    args=parser.parse_args()
    import numpy as np
    import torch
    import trimesh
    from PIL import Image,ImageOps
    if not torch.cuda.is_available():raise RuntimeError('cuda_unavailable')
    torch.set_num_threads(4);torch.manual_seed(args.seed);torch.cuda.reset_peak_memory_stats()
    started=time.perf_counter()
    with Image.open(args.input) as original:image=ImageOps.exif_transpose(original).convert('RGBA' if args.mode=='reconstruct' else 'RGB')
    source=args.root/'runtime/upstream'/('TripoSR' if args.backend=='triposr' else 'TRELLIS.2')
    sys.path.insert(0,str(source))
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
        mesh.export(args.output/'raw_mesh.ply')
        parameters={'mc_resolution':128,'chunk_size':2048,'foreground_ratio':.85,'background':'gray','coordinates':'native_z_up'}
    else:
        from trellis2.pipelines import Trellis2ImageTo3DPipeline
        model=Trellis2ImageTo3DPipeline.from_pretrained('microsoft/TRELLIS.2-4B');model.cuda()
        torch.cuda.synchronize();loaded=time.perf_counter()
        prepared=model.preprocess_image(image);prepared.save(args.output/'backend_input.png')
        with torch.inference_mode():
            output=model.run(prepared,seed=args.seed,preprocess_image=False,pipeline_type='1024_cascade')[0]
        torch.cuda.synchronize();inferred=time.perf_counter()
        mesh=trimesh.Trimesh(vertices=output.vertices.detach().cpu().numpy(),faces=output.faces.detach().cpu().numpy(),process=False)
        mesh.export(args.output/'raw_mesh.ply')
        parameters={'pipeline_type':'1024_cascade','preprocessing':'official_alpha_crop_black_composite','coordinates':'native_z_up_no_glb_axis_conversion',
            'upstream_internal_processing':'pipeline decoding unchanged; no PBR video or postprocess.to_glb'}
    torch.cuda.synchronize()
    report={'mode':args.mode,'backend':args.backend,'seed':args.seed,'parameters':parameters,'torch':torch.__version__,
        'cuda_runtime':torch.version.cuda,'device':torch.cuda.get_device_name(0),'input_file':args.input.name,
        'seconds':{'load_and_prepare':loaded-started,'inference':inferred-loaded,'total':time.perf_counter()-started},
        'timing_scope':'inference includes backend image processing and model decoding; process startup is separately recorded',
        'peak_allocated_mib':torch.cuda.max_memory_allocated()/2**20,'peak_reserved_mib':torch.cuda.max_memory_reserved()/2**20}
    (args.output/'model.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
