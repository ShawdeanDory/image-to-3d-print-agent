"""记录基础依赖和CPU冒烟；不加载模型、调用GPU或编译扩展。"""
import argparse
import importlib
import importlib.metadata as metadata
import io
import json
import os
import platform
from pathlib import Path


PACKAGES = {
    "torch": "torch", "torchvision": "torchvision", "triton": "triton",
    "numpy": "numpy", "imageio": "imageio", "imageio-ffmpeg": "imageio_ffmpeg",
    "tqdm": "tqdm", "easydict": "easydict", "opencv-python-headless": "cv2",
    "ninja": "ninja", "trimesh": "trimesh", "transformers": "transformers",
    "gradio": "gradio", "tensorboard": "tensorboard", "pandas": "pandas",
    "lpips": "lpips", "zstandard": "zstandard", "kornia": "kornia",
    "timm": "timm", "packaging": "packaging", "psutil": "psutil",
    "wheel": "wheel", "setuptools": None, "utils3d": "utils3d",
    "pillow-simd": "PIL", "moderngl": "moderngl", "plyfile": "plyfile",
    "scipy": "scipy",
}
DEFERRED = ["flash-attn", "nvdiffrast", "nvdiffrec", "cumesh", "flex-gemm", "o-voxel"]


def version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def main():
    # 本检查只能使用已安装库；禁止隐式取权重和界面遥测。
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=["baseline", "installed"])
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {
        "phase": args.phase, "python": platform.python_version(),
        "versions": {name: version(name) for name in PACKAGES},
        "deferred_versions": {name: version(name) for name in DEFERRED},
        "imports": {}, "errors": [], "gpu_operations": "not_run",
        "model_load": "not_run", "cuda_extension_compile": "not_run",
    }
    if args.phase == "installed":
        expected = {"torch": "2.6.0+cu124", "torchvision": "0.21.0+cu124",
                    "triton": "3.2.0", "transformers": "4.57.6", "gradio": "6.0.1"}
        if platform.python_version_tuple()[:2] != ("3", "10"):
            report["errors"].append("Python版本不是3.10")
        for name, want in expected.items():
            if report["versions"][name] != want:
                report["errors"].append(f"版本不符：{name}")
        for name, module in PACKAGES.items():
            try:
                if report["versions"][name] is None:
                    raise ImportError("distribution missing")
                if module:
                    importlib.import_module(module)
                report["imports"][name] = "passed"
            except Exception as exc:
                report["imports"][name] = "failed"
                report["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
        try:
            import torch
            from PIL import Image, features
            from transformers import AutoModelForImageSegmentation, DINOv3ViTModel
            tensor = torch.tensor([[1., 2.], [3., 4.]], device="cpu")
            assert (tensor @ tensor).tolist() == [[7., 10.], [15., 22.]]
            data = io.BytesIO()
            Image.new("RGB", (4, 4), "red").save(data, format="PNG")
            data.seek(0)
            image = Image.open(data)
            assert image.size == (4, 4) and image.getpixel((0, 0)) == (255, 0, 0)
            assert features.check("jpg"), "JPEG支持缺失"
            report["cpu_checks"] = {"torch_matmul": "passed", "png_roundtrip": "passed",
                                    "transformers_classes": "passed", "jpeg_support": features.check("jpg"),
                                    "torch_cuda_runtime": torch.version.cuda,
                                    "pil_import_version": Image.__version__}
        except Exception as exc:
            report["errors"].append(f"CPU冒烟: {type(exc).__name__}: {exc}")
    report["status"] = "passed" if not report["errors"] else "failed"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
