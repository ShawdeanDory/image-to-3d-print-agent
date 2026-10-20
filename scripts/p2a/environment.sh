#!/usr/bin/env bash
# 安装脚本共用的数据盘路径；不修改基础镜像的默认Python。
set -euo pipefail
export PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export HF_HOME="$PROJECT_ROOT/runtime/cache/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export PIP_CACHE_DIR="$PROJECT_ROOT/runtime/cache/pip"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/runtime/cache/conda"
export TMPDIR="$PROJECT_ROOT/runtime/tmp"
export TORCH_EXTENSIONS_DIR="$PROJECT_ROOT/runtime/torch_extensions"
export CUDA_HOME=/usr/local/cuda
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TORCH_CUDA_ARCH_LIST=8.9
export MAX_JOBS=4
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_RETRIES=0
export PYTHONUNBUFFERED=1
export P2A_RUN_DIR="${P2A_RUN_DIR:-$PROJECT_ROOT/runs/p2a-20261020-03}"
mkdir -p "$HF_HUB_CACHE" "$PIP_CACHE_DIR" "$CONDA_PKGS_DIRS" "$TMPDIR" "$TORCH_EXTENSIONS_DIR" "$PROJECT_ROOT/runtime/envs" "$PROJECT_ROOT/runtime/upstream"
mkdir -p "$P2A_RUN_DIR"
source /root/miniconda3/etc/profile.d/conda.sh
cd "$PROJECT_ROOT"
