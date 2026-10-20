"""验证CUDA张量与真实CUDA表面提取；失败不切换CPU。"""
import json
import time


def main():
    import torch
    import torchmcubes
    started = time.perf_counter()
    if not torch.cuda.is_available() or not torchmcubes.HAS_CUDA:
        raise RuntimeError("CUDA或CUDA版torchmcubes不可用")
    matrix = torch.arange(64, dtype=torch.float32).reshape(8, 8)
    result = matrix.cuda() @ matrix.cuda().T
    torch.testing.assert_close(result.cpu(), matrix @ matrix.T)
    axis = torch.linspace(-1, 1, 16, device="cuda")
    x, y, z = torch.meshgrid(axis, axis, axis, indexing="ij")
    field = (x.square() + y.square() + z.square() - 0.5).contiguous()
    vertices, faces = torchmcubes.marching_cubes(field, 0.0)
    assert vertices.is_cuda and faces.is_cuda
    assert len(vertices) > 0 and len(faces) > 0
    assert torch.isfinite(vertices).all().item()
    assert faces.min().item() >= 0 and faces.max().item() < len(vertices)
    torch.cuda.synchronize()
    print(json.dumps({"kind": "cuda_tensor_and_extension", "status": "passed",
                      "torch": torch.__version__, "cuda_runtime": torch.version.cuda,
                      "device": torch.cuda.get_device_name(0),
                      "compute_capability": torch.cuda.get_device_capability(0),
                      "marching_cubes_cuda_compiled": torchmcubes.HAS_CUDA,
                      "vertices": len(vertices), "faces": len(faces),
                      "seconds": time.perf_counter() - started}))


if __name__ == "__main__":
    main()
