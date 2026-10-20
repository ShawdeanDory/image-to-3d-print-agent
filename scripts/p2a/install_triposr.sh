#!/usr/bin/env bash
# 本脚本由外层screen与剩余总预算timeout包裹运行。
set -euo pipefail
source "$(dirname "$0")/environment.sh"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/runtime/cache/conda-triposr"
mkdir -p "$CONDA_PKGS_DIRS"
python_base=/root/miniconda3/bin/python
"$python_base" scripts/p2a/prepare_source.py TripoSR
"$python_base" scripts/p2a/prepare_source.py torchmcubes
if [ ! -x "$PROJECT_ROOT/runtime/envs/triposr/bin/python" ]; then
    conda create -y -p "$PROJECT_ROOT/runtime/envs/triposr" python=3.11 pip
fi
conda activate "$PROJECT_ROOT/runtime/envs/triposr"
python -c 'import sys; assert sys.version_info[:2] == (3, 11)'
python -m pip install numpy==1.26.4 Pillow==10.1.0
python -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
python -m pip install numpy==1.26.4 omegaconf==2.3.0 Pillow==10.1.0 einops==0.7.0 transformers==4.35.0 trimesh==4.0.5 rembg==2.0.57 huggingface-hub==0.17.3 onnxruntime==1.18.1 opencv-python-headless==4.10.0.84 xatlas==0.0.9 moderngl==5.10.0 'imageio[ffmpeg]' setuptools==69.5.1 cmake==3.29.6 pybind11==3.1.0 scikit-build-core==1.1.1 ninja
python scripts/p2a/prepare_torchmcubes_build.py
python -m pip install --no-build-isolation "$PROJECT_ROOT/runtime/build/torchmcubes-cxx17"
python -m pip check
python -m pip freeze > "$P2A_RUN_DIR/triposr-pip-freeze.txt"
conda list --explicit > "$P2A_RUN_DIR/triposr-conda-explicit.txt"
