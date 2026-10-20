#!/usr/bin/env bash
# 本脚本由外层screen与剩余总预算timeout包裹运行。
set -euo pipefail
source "$(dirname "$0")/environment.sh"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/runtime/cache/conda-triposr"
mkdir -p "$CONDA_PKGS_DIRS"
python_base=/root/miniconda3/bin/python
"$python_base" scripts/p2a/prepare_source.py TripoSR
"$python_base" scripts/p2a/prepare_source.py torchmcubes
conda create -y -p "$PROJECT_ROOT/runtime/envs/triposr" python=3.11 pip
conda activate "$PROJECT_ROOT/runtime/envs/triposr"
python -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
python -m pip install numpy==1.26.4 omegaconf==2.3.0 Pillow==10.1.0 einops==0.7.0 transformers==4.35.0 trimesh==4.0.5 rembg==2.0.57 huggingface-hub==0.17.3 onnxruntime==1.18.1 xatlas==0.0.9 moderngl==5.10.0 'imageio[ffmpeg]' setuptools==69.5.1 cmake==3.29.6 pybind11==3.1.0 ninja
python -m pip install --no-build-isolation "$PROJECT_ROOT/runtime/upstream/torchmcubes"
python -m pip check
python -m pip freeze > runs/p2a-20261020-02/triposr-pip-freeze.txt
conda list --explicit > runs/p2a-20261020-02/triposr-conda-explicit.txt
