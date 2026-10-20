#!/usr/bin/env bash
# 外层仍受剩余总预算限制，每次GPU验证最多300秒。
set -euo pipefail
source "$(dirname "$0")/environment.sh"
conda activate "$PROJECT_ROOT/runtime/envs/triposr"
timeout --signal=TERM --kill-after=10s 300s python scripts/p2a/check_triposr_cuda.py > "$P2A_RUN_DIR/triposr-cuda-check.json"
for case_name in hamburger robot; do
    output="$P2A_RUN_DIR/triposr-$case_name"
    if [ -e "$output" ]; then
        echo "输出目录已存在，不自动重跑：$case_name" >&2
        exit 1
    fi
    timeout --signal=TERM --kill-after=10s 300s python scripts/p0/reconstruct_case.py \
        --root "$PROJECT_ROOT" --image "$PROJECT_ROOT/fixtures/p0/$case_name.png" --output "$output"
    "$PROJECT_ROOT/runtime/envs/probe/bin/python" scripts/p2a/read_mesh.py \
        "$output/raw_mesh.glb" --output "$output/independent_read.json"
done
