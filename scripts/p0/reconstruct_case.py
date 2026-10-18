"""通过上游TripoSR公开Python接口执行一张P0固定样例。"""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(root / "runtime/cache/huggingface")
    os.environ["HF_HUB_OFFLINE"] = "1"
    sys.path.insert(0, str(root / "runtime/upstream/TripoSR"))

    import numpy as np
    import torch
    import torchmcubes
    from PIL import Image
    from tsr.system import TSR
    from tsr.utils import resize_foreground

    if not torch.cuda.is_available():
        raise RuntimeError("P0要求本机CUDA验证，不允许静默切换CPU模型")
    torch.manual_seed(0)
    torch.set_num_threads(4)
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = TSR.from_pretrained(str(root / "weights/TripoSR"),
                                config_name="config.yaml", weight_name="model.ckpt")
    model.renderer.set_chunk_size(2048)
    model.eval().to("cuda:0")
    torch.cuda.synchronize()
    loaded = time.perf_counter()
    image = Image.open(args.image)
    if image.mode != "RGBA" or image.getextrema()[3][0] == 255:
        raise ValueError("本次P0固定输入必须已有透明前景；不隐式下载或调用抠图模型")
    image = resize_foreground(image, .85)
    rgba = np.asarray(image).astype(np.float32) / 255
    rgb = rgba[:, :, :3] * rgba[:, :, 3:] + (1 - rgba[:, :, 3:]) * .5
    image = Image.fromarray((rgb * 255).astype(np.uint8))
    image.save(args.output / "processed_input.png")
    preprocessed = time.perf_counter()
    with torch.inference_mode():
        scene_codes = model([image], device="cuda:0")
    torch.cuda.synchronize()
    inferred = time.perf_counter()
    # 无CUDA编译器时上游torchmcubes使用CPU提取等值面；神经网络仍在CUDA上运行。
    with torch.inference_mode():
        mesh = model.extract_mesh(scene_codes, has_vertex_color=True, resolution=128)[0]
    torch.cuda.synchronize()
    extracted = time.perf_counter()
    mesh.export(args.output / "raw_mesh.glb")
    result = {
        "input": str(args.image.relative_to(root)),
        "model_device": str(next(model.parameters()).device),
        "scene_code_device": str(scene_codes.device),
        "marching_cubes_cuda_compiled": bool(torchmcubes.HAS_CUDA),
        "parameters": {"chunk_size": 2048, "mc_resolution": 128,
                       "foreground_ratio": .85, "dtype": "float32", "seed": 0,
                       "preprocessing": "existing_alpha_resize_and_gray_composite"},
        "seconds": {"load_and_cuda_transfer": loaded - started,
                    "preprocessing": preprocessed - loaded,
                    "neural_inference": inferred - preprocessed,
                    "mesh_extraction": extracted - inferred,
                    "total": time.perf_counter() - started},
        "peak_cuda_allocated_mib": torch.cuda.max_memory_allocated() / 2**20,
        "peak_cuda_reserved_mib": torch.cuda.max_memory_reserved() / 2**20,
        "torch_version": torch.__version__, "cuda_runtime": torch.version.cuda,
        "vertices": len(mesh.vertices), "faces": len(mesh.faces),
        "raw_mesh": str((args.output / "raw_mesh.glb").relative_to(root)),
    }
    (args.output / "reconstruction.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
