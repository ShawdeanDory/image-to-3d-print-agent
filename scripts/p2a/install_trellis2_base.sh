#!/usr/bin/env bash
# 只准备官方basic组及框架轮子；CUDA扩展与模型不在本入口执行。
set -euo pipefail
source "$(dirname "$0")/environment.sh"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/runtime/cache/conda-trellis2"
export PIP_TIMEOUT=30
export PIP_INDEX_URL=https://mirrors.ustc.edu.cn/pypi/simple
mkdir -p "$CONDA_PKGS_DIRS"
if [ ! -x "$PROJECT_ROOT/runtime/envs/trellis2/bin/python" ]; then
    conda create -y -p "$PROJECT_ROOT/runtime/envs/trellis2" python=3.10 pip
fi
conda activate "$PROJECT_ROOT/runtime/envs/trellis2"
python -c 'import sys; assert sys.version_info[:2] == (3, 10)'
python - <<'PY'
import json, pathlib, subprocess
root = pathlib.Path.cwd()
plan = json.loads((root / 'locks/p2a-source-plan.json').read_text())
for name in ['TRELLIS.2', 'utils3d']:
    item = next(item for item in plan['sources'] if item['name'] == name)
    source = root / 'runtime/upstream' / name
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    assert actual == item['revision'], (name, actual)
    assert not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain']), name
PY
if [ ! -f "$P2A_RUN_DIR/base-baseline.json" ]; then
    python scripts/p2a/check_trellis2_base.py --phase baseline --report "$P2A_RUN_DIR/base-baseline.json"
fi
# triton只安装现成轮子，先完成它以避免Torch索引低速节点。
python scripts/p2a/prepare_triton_wheel.py
python -m pip install --no-index --no-deps "$PROJECT_ROOT/runtime/wheels/triton-3.2.0-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
python -m pip install --only-binary=:all: 'https://download.pytorch.org/whl/cu124/torch-2.6.0%2Bcu124-cp310-cp310-linux_x86_64.whl#sha256=7f2ba7f7c0459320a521696f6b5bccc187f59890b23c9dfb6c49b0b87c6bfc97' torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
# DINOv3所需transformers固定为4.57.6；实际兼容性只验收到CPU导入。
python -m pip install --only-binary=:all: imageio imageio-ffmpeg tqdm easydict opencv-python-headless==4.10.0.84 ninja trimesh transformers==4.57.6 gradio==6.0.1 tensorboard pandas lpips zstandard kornia timm packaging psutil wheel setuptools==80.9.0 moderngl plyfile scipy
# 此固定utils3d是纯Python包，独立于后续CUDA扩展。
python -m pip install --no-deps --no-build-isolation "$PROJECT_ROOT/runtime/upstream/utils3d"
if ! dpkg-query -W -f='${Status}' libjpeg-dev 2>/dev/null | grep -q 'install ok installed'; then
    apt-get update
    apt-get install -y --no-install-recommends libjpeg-dev
fi
# Pillow-SIMD仅为CPU图像库构建，不调用CUDA编译器。
python -m pip install pillow-simd
python -m pip check
python scripts/p2a/check_trellis2_base.py --phase installed --report "$P2A_RUN_DIR/base-check.json"
python -m pip freeze > "$P2A_RUN_DIR/trellis2-base-pip-freeze.txt"
conda list --explicit > "$P2A_RUN_DIR/trellis2-base-conda-explicit.txt"
