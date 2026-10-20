#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/environment.sh"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/runtime/cache/conda-probe"
mkdir -p "$CONDA_PKGS_DIRS"
conda create -y -p "$PROJECT_ROOT/runtime/envs/probe" python=3.11 pip
conda activate "$PROJECT_ROOT/runtime/envs/probe"
python -m pip install numpy==1.26.4 trimesh==4.0.5 huggingface-hub==0.36.0
python -m pip check
python -m pip freeze > runs/p2a-20261020-02/probe-pip-freeze.txt
conda list --explicit > runs/p2a-20261020-02/probe-conda-explicit.txt
