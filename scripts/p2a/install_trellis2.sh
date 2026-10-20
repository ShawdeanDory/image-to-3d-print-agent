#!/usr/bin/env bash
# 按固定官方源码准备候选环境；逐条失败即停止。
set -euo pipefail
source "$(dirname "$0")/environment.sh"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/runtime/cache/conda-trellis2"
mkdir -p "$CONDA_PKGS_DIRS"
for source_name in TRELLIS.2 utils3d nvdiffrast nvdiffrec CuMesh FlexGEMM; do
    /root/miniconda3/bin/python scripts/p2a/prepare_source.py "$source_name"
done
if [ ! -x "$PROJECT_ROOT/runtime/envs/trellis2/bin/python" ]; then
    conda create -y -p "$PROJECT_ROOT/runtime/envs/trellis2" python=3.10 pip
fi
conda activate "$PROJECT_ROOT/runtime/envs/trellis2"
python -c 'import sys; assert sys.version_info[:2] == (3, 10)'
python -m pip install triton==3.2.0
# 官方索引的r2节点过慢；同版本原官方路径，按索引SHA256核验。
python -m pip install 'https://download.pytorch.org/whl/cu124/torch-2.6.0%2Bcu124-cp310-cp310-linux_x86_64.whl#sha256=7f2ba7f7c0459320a521696f6b5bccc187f59890b23c9dfb6c49b0b87c6bfc97' torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
python -m pip install imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja trimesh transformers gradio==6.0.1 tensorboard pandas lpips zstandard kornia timm packaging psutil wheel
python -m pip install "$PROJECT_ROOT/runtime/upstream/utils3d"
if ! dpkg-query -W -f='${Status}' libjpeg-dev 2>/dev/null | grep -q 'install ok installed'; then
    apt-get update
    apt-get install -y --no-install-recommends libjpeg-dev
fi
python -m pip install pillow-simd
python -m pip install flash-attn==2.7.3 --no-build-isolation
for source_name in nvdiffrast nvdiffrec CuMesh FlexGEMM; do
    python -m pip install --no-build-isolation "$PROJECT_ROOT/runtime/upstream/$source_name"
done
python -m pip install --no-build-isolation "$PROJECT_ROOT/runtime/upstream/TRELLIS.2/o-voxel"
python -m pip check
python -m pip freeze > "$P2A_RUN_DIR/trellis2-pip-freeze.txt"
conda list --explicit > "$P2A_RUN_DIR/trellis2-conda-explicit.txt"
