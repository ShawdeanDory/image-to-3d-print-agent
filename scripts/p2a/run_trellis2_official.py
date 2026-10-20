"""原样运行固定官方example.py，保存实际结果、时间和显存。"""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    os.environ["HF_HOME"] = str(root / "runtime/cache/huggingface")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    import torch

    # 无卡时在导入候选管线、创建输出或加载权重前退出。
    if not torch.cuda.is_available():
        print(json.dumps({"status": "not_run", "reason": "cuda_unavailable", "model_loading": "not_run"}))
        return 2
    upstream = root / "runtime/upstream/TRELLIS.2"
    plan = json.loads((root / "locks/p2a-source-plan.json").read_text(encoding="utf-8"))
    expected = next(item["revision"] for item in plan["sources"] if item["name"] == "TRELLIS.2")
    actual = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    assert actual == expected, "官方源码revision不符"
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("输出目录非空，不覆盖已有官方示例结果")
    output.mkdir(parents=True, exist_ok=True)
    (output / "assets").symlink_to(upstream / "assets", target_is_directory=True)
    sys.path.insert(0, str(upstream))
    original_directory = Path.cwd()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    report = {"kind": "trellis2_official_example", "upstream_revision": expected, "process_id": os.getpid(),
              "torch": torch.__version__, "cuda_runtime": torch.version.cuda,
              "gpu": torch.cuda.get_device_name(0), "parameters": "原官方example.py默认参数",
              "timing_scope": "含模型加载、推理、PBR视频和GLB导出，不含Python启动与Torch导入"}
    try:
        os.chdir(output)
        runpy.run_path(str(upstream / "example.py"), run_name="__main__")
        torch.cuda.synchronize()
        assert (output / "sample.glb").stat().st_size > 0
        assert (output / "sample.mp4").stat().st_size > 0
        report["status"] = "succeeded"
        code = 0
    except Exception as error:
        traceback.print_exc()
        report.update(status="failed", error_type=type(error).__name__, error=str(error))
        code = 1
    finally:
        os.chdir(original_directory)
        report.update(seconds=time.perf_counter() - started,
                      allocated_peak_MiB=torch.cuda.max_memory_allocated() / 1024**2,
                      reserved_peak_MiB=torch.cuda.max_memory_reserved() / 1024**2)
        (output / "official-run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
