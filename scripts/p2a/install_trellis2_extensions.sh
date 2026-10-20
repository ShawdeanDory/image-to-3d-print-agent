#!/usr/bin/env bash
# 准备入口：恢复正常实例CPU/内存配额后执行；本轮无卡模式只做语法检查。
set -euo pipefail
source "$(dirname "$0")/environment.sh"
conda activate "$PROJECT_ROOT/runtime/envs/trellis2"
python - <<'PY'
import sys, torch, importlib.metadata as metadata
assert sys.version_info[:2] == (3, 10)
assert torch.__version__ == '2.6.0+cu124'
assert metadata.version('torchvision') == '0.21.0+cu124'
assert metadata.version('flash-attn') == '2.7.3', '先复用本轮固定官方FlashAttention轮子'
PY
for source_name in nvdiffrast nvdiffrec CuMesh FlexGEMM; do
    /root/miniconda3/bin/python scripts/p2a/prepare_source.py "$source_name"
    python -m pip install --no-deps --no-build-isolation "$PROJECT_ROOT/runtime/upstream/$source_name"
done
/root/miniconda3/bin/python scripts/p2a/prepare_source.py TRELLIS.2
python -m pip install --no-deps --no-build-isolation "$PROJECT_ROOT/runtime/upstream/TRELLIS.2/o-voxel"
python -m pip check
python -m pip freeze > "$P2A_RUN_DIR/trellis2-native-pip-freeze.txt"
conda list --explicit > "$P2A_RUN_DIR/trellis2-native-conda-explicit.txt"
