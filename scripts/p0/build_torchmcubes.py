"""在独立同版本CPU环境编译扩展，再装入CUDA重建环境；仅用于P0。"""
import json
import os
from pathlib import Path
import subprocess
import time


root = Path(__file__).resolve().parents[2]
folder = root / "runs/p0/p0-20261018-01"
folder.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, UV_CACHE_DIR=str(root / "runtime/cache/uv"),
           UV_LINK_MODE="copy", PYTHONIOENCODING="utf-8", CMAKE_BUILD_PARALLEL_LEVEL="1")
vs = Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat")
if not vs.exists():
    raise FileNotFoundError("当前复现脚本对应本次记录的Visual Studio2022路径；换机器先核对环境")
setup = subprocess.run(
    f'cmd.exe /d /s /c ""{vs}" -arch=x64 -host_arch=x64 >nul && set"',
    capture_output=True, text=True, errors="replace", timeout=30)
if setup.returncode:
    raise RuntimeError("MSVC环境初始化失败：" + setup.stderr)
for line in setup.stdout.splitlines():
    if "=" in line and not line.startswith("="):
        key, value = line.split("=", 1)
        env[key] = value
for key in list(env):
    if key.lower() == "path":
        old_path = env.pop(key)
        break
env["PATH"] = str(root / "runtime/envs/build-cpu/Scripts") + os.pathsep + old_path
wheel_dir = root / "runtime/wheels"
wheel_dir.mkdir(parents=True, exist_ok=True)
command = [str(root / "runtime/envs/build-cpu/Scripts/python.exe"), "-m", "pip", "wheel",
           "--no-build-isolation", "--no-deps", "--wheel-dir", str(wheel_dir),
           "--config-settings=build-dir=build-cpu-p0", str(root / "runtime/upstream/torchmcubes")]
started = time.perf_counter()
with (folder / "build_torchmcubes_cpu.log").open("w", encoding="utf-8") as stream:
    try:
        process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=600)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        returncode = 124
summary = {"command": command, "returncode": returncode,
           "seconds": time.perf_counter() - started, "build_torch": "2.5.1+cpu",
           "runtime_torch": "2.5.1+cu121", "cuda_kernels_compiled": False}
(folder / "build_torchmcubes_cpu.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False), flush=True)
if returncode:
    raise SystemExit(returncode)
wheels = list(wheel_dir.glob("torchmcubes-*.whl"))
if len(wheels) != 1:
    raise RuntimeError("应恰有一份本次扩展轮子，先核对runtime/wheels内容")
install = [str(root / "runtime/tools/uv/uv.exe"), "pip", "install", "--python",
           str(root / "runtime/envs/reconstruction/Scripts/python.exe"), "--no-deps", str(wheels[0])]
subprocess.run(install, env=env, check=True, timeout=120)
