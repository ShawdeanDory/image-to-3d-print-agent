"""本机选图试用入口；复用P0重建，不实现业务Agent或公共schema。"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime


ROOT = Path(__file__).resolve().parents[2]


def validate_image(path):
    from PIL import Image
    try:
        with Image.open(path) as image:
            if image.format not in {"PNG", "JPEG"}:
                raise ValueError("请选择真实的PNG或JPEG图片")
            result = {"format": image.format, "size": list(image.size)}
            image.verify()
            return result
    except (OSError, SyntaxError) as exc:
        raise ValueError("图片不存在、损坏或无法读取") from exc


def new_run_dir(root):
    parent = root / "runs/manual"
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=parent))


def run_step(command, log_path, timeout, env=None):
    with log_path.open("w", encoding="utf-8") as stream:
        try:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, env=env, shell=False)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"操作超过{timeout}秒，已停止。日志：{log_path}") from exc
    if result.returncode:
        raise RuntimeError(f"操作失败，退出码{result.returncode}。日志：{log_path}")


def choose_image():
    import tkinter as tk
    from tkinter import filedialog
    window = tk.Tk()
    window.title("本机图片到3D模型")
    window.geometry("480x110")
    tk.Label(window, text="请选择一张物体图片，取消即可退出。", font=("Microsoft YaHei UI", 11)).pack(pady=35)
    window.attributes("-topmost", True)
    window.update()
    try:
        return filedialog.askopenfilename(parent=window, title="选择要生成3D模型的图片",
                                         initialdir=str(ROOT / "data" if (ROOT / "data").is_dir() else ROOT),
                                         filetypes=[("PNG/JPEG图片", "*.png *.jpg *.jpeg")])
    finally:
        window.destroy()


def open_blender(root, mesh, folder):
    blender = root / "runtime/tools/blender/blender-4.5.14-windows-x64/blender.exe"
    ready = folder / "blender_import.json"
    command = [str(blender), "--factory-startup", "--python-exit-code", "1", "--python",
               str(root / "scripts/local_preview/open_result.py"), "--", str(mesh), str(ready)]
    with (folder / "blender.log").open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, shell=False,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if ready.exists():
                return json.loads(ready.read_text(encoding="utf-8"))
            if process.poll() is not None:
                raise RuntimeError(f"Blender未能导入结果。日志：{folder / 'blender.log'}")
            time.sleep(.2)
        process.terminate()
        process.wait(timeout=10)
        raise TimeoutError(f"Blender导入超过120秒。日志：{folder / 'blender.log'}")


def main():
    parser = argparse.ArgumentParser(description="选择本机图片，生成GLB并在Blender查看")
    parser.add_argument("--image", type=Path, help="直接指定图片；省略时弹出文件选择器")
    parser.add_argument("--no-open", action="store_true", help="只生成，用于无界面复现")
    args = parser.parse_args()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, True, "Local\\ImageTo3DPrintLocalPreview")
    if not mutex:
        raise RuntimeError("无法建立本机任务锁")
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        raise RuntimeError("已有本机生成任务正在运行，请完成后再试")
    folder = None
    summary = {}
    try:
        print("本机图片到3D试用；完成后会打开Blender。", flush=True)
        selected = str(args.image) if args.image else choose_image()
        if not selected:
            print("已取消，没有运行模型。", flush=True)
            return 0
        image = Path(selected).resolve()
        metadata = validate_image(image)
        for required in [ROOT / "weights/TripoSR/model.ckpt", ROOT / "weights/TripoSR/config.yaml",
                         ROOT / "scripts/p0/reconstruct_case.py",
                         ROOT / "runtime/tools/blender/blender-4.5.14-windows-x64/blender.exe"]:
            if not required.is_file():
                raise FileNotFoundError(f"缺少本机环境文件：{required}")
        folder = new_run_dir(ROOT)
        source = folder / ("source.png" if metadata["format"] == "PNG" else "source.jpg")
        shutil.copy2(image, source)
        summary = {"source_image": str(image), "input": metadata, "status": "running",
                   "parameters": {"chunk_size": 2048, "mc_resolution": 128, "model_device": "cuda:0"}}
        env = dict(os.environ, HF_HOME=str(ROOT / "runtime/cache/huggingface"), HF_HUB_OFFLINE="1",
                   U2NET_HOME=str(ROOT / "runtime/cache/u2net"), PYTHONIOENCODING="utf-8")
        prepared = folder / "prepared.png"
        print(f"结果目录：{folder}\n正在准备图片，首次自动去背景可能需要下载权重。", flush=True)
        run_step([sys.executable, str(ROOT / "scripts/local_preview/prepare_image.py"),
                  str(source), str(prepared)], folder / "prepare.log", 600, env)
        print("正在调用本机GPU生成模型，最长300秒。", flush=True)
        started = time.monotonic()
        run_step([sys.executable, str(ROOT / "scripts/p0/reconstruct_case.py"), "--root", str(ROOT),
                  "--image", str(prepared), "--output", str(folder)], folder / "reconstruction.log", 300, env)
        summary["reconstruction_seconds"] = time.monotonic() - started
        mesh_path = folder / "raw_mesh.glb"
        import numpy as np
        import trimesh
        mesh = trimesh.load(mesh_path, force="mesh", process=False)
        if not len(mesh.vertices) or not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
            raise RuntimeError("重建输出不是有效的非空网格")
        summary.update(status="generated", mesh=str(mesh_path), vertices=len(mesh.vertices),
                       faces=len(mesh.faces), watertight=bool(mesh.is_watertight))
        print(f"已生成：{mesh_path}", flush=True)
        if not args.no_open:
            print("正在打开Blender并导入模型。", flush=True)
            summary["blender"] = open_blender(ROOT, mesh_path, folder)
            summary["status"] = "opened"
            print("Blender已导入，可以旋转和缩放查看。", flush=True)
        print("本次为原始重建预览，尚未定标或完成打印检查。", flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        summary.update(status="cancelled" if isinstance(exc, KeyboardInterrupt) else "failed",
                       error=str(exc) or "用户中断")
        print(f"未完成：{summary['error']}", flush=True)
        return 1
    finally:
        if folder is not None:
            (folder / "run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        kernel.ReleaseMutex(mutex)
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"无法启动：{exc}", flush=True)
        raise SystemExit(1)
