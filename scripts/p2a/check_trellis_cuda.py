"""验证候选环境的CUDA与关键原生工具；不加载受限模型或判定可打印。"""
import json
from pathlib import Path
import sys
import time


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "runtime/upstream/TRELLIS.2"))
    import torch
    from flash_attn import flash_attn_func
    import nvdiffrast.torch as dr
    import cumesh
    import flex_gemm
    import o_voxel
    import nvdiffrec_render
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    started = time.perf_counter()
    if not torch.cuda.is_available():
        raise RuntimeError("候选环境无法使用CUDA")
    torch.manual_seed(0)
    q, k, v = [torch.randn(1, 16, 2, 32, device="cuda", dtype=torch.float16) for _ in range(3)]
    output = flash_attn_func(q, k, v)
    q_cpu, k_cpu, v_cpu = [x.cpu().double().transpose(1, 2) for x in [q, k, v]]
    expected = ((q_cpu @ k_cpu.transpose(-2, -1) / 32**0.5).softmax(-1) @ v_cpu).transpose(1, 2)
    torch.testing.assert_close(output.cpu().double(), expected, rtol=0.02, atol=0.02)
    position = torch.tensor([[[-0.8, -0.8, 0.0, 1.0], [0.8, -0.8, 0.0, 1.0], [0.0, 0.8, 0.0, 1.0]]], device="cuda")
    triangles = torch.tensor([[0, 1, 2]], dtype=torch.int32, device="cuda")
    raster, _ = dr.rasterize(dr.RasterizeCudaContext(), position, triangles, resolution=[16, 16])
    assert torch.isfinite(raster).all().item() and raster[..., 3].max().item() > 0
    vertices = torch.tensor([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]], device="cuda")
    faces = torch.tensor([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=torch.int32, device="cuda")
    mesh = cumesh.CuMesh()
    mesh.init(vertices, faces)
    mesh.compute_face_normals()
    read_vertices, read_faces = mesh.read()
    assert len(read_vertices) == 4 and len(read_faces) == 4
    torch.cuda.synchronize()
    print(json.dumps({"kind": "trellis_cuda_environment", "torch": torch.__version__,
                      "cuda_runtime": torch.version.cuda, "device": torch.cuda.get_device_name(0),
                      "flash_attention_numeric_check": "passed", "nvdiffrast_cuda_raster": "passed",
                      "cumesh_cuda_init_normals_read": "passed",
                      "flex_gemm_o_voxel_renderutils_pipeline_import": "passed",
                      "model_loading": "not_run_gated_dependencies_missing",
                      "seconds": time.perf_counter() - started}))


if __name__ == "__main__":
    main()
