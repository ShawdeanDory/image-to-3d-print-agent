"""只读采集P2-A安装前环境；不安装依赖、不执行CUDA张量或模型。"""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def command(arguments):
    try:
        result = subprocess.run(arguments, text=True, capture_output=True, timeout=15)
        return {"exit_code": result.returncode, "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"error_type": type(error).__name__, "detail": str(error)}


def main():
    conda = Path(sys.executable).with_name("conda")
    nvcc = shutil.which("nvcc")
    if nvcc is None:
        for candidate in ["/usr/local/cuda/bin/nvcc", "/usr/local/cuda-12.4/bin/nvcc"]:
            if Path(candidate).is_file():
                nvcc = candidate
                break
    report = {
        "kind": "read_only_preinstallation", "python": sys.version,
        "python_executable": sys.executable, "platform": platform.platform(),
        "conda": command([str(conda), "--version"]) if conda.is_file() else None,
        "nvcc_path": nvcc,
        "nvcc": command([nvcc, "--version"]) if nvcc else None,
        "cpu_affinity": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "system": Path("/etc/os-release").read_text(),
        "disk": command(["df", "-h", "/", "/root/autodl-tmp"]),
        "gpu": command(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader"]),
        "tools": {name: shutil.which(name) for name in ["git", "screen", "gcc", "g++"]},
        "cgroup": {},
    }
    for relative in ["memory.max", "memory.current", "cpu.max", "memory/memory.limit_in_bytes",
                     "cpu/cpu.cfs_quota_us", "cpu/cpu.cfs_period_us"]:
        path = Path("/sys/fs/cgroup") / relative
        if path.is_file():
            report["cgroup"][relative] = path.read_text().strip()
    try:
        import torch
        report["torch"] = {"version": torch.__version__, "cuda": torch.version.cuda,
                           "gpu_available": torch.cuda.is_available()}
    except Exception as error:
        report["torch"] = {"error_type": type(error).__name__, "detail": str(error)}
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
