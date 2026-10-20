#!/usr/bin/env bash
# 仅为传入的HF命令加载AutoDL官方代理及其配套CA，不修改系统配置。
set -eo pipefail
if [ "$#" -eq 0 ]; then
    echo "用法：bash scripts/p2a/with_hf_network.sh 命令 参数..." >&2
    exit 2
fi
if ! source /etc/network_turbo >/dev/null 2>&1; then
    echo "无法加载AutoDL官方网络配置" >&2
    exit 1
fi
set -u
if [ ! -r "${SSL_CERT_FILE:-}" ] || [ ! -r "${REQUESTS_CA_BUNDLE:-}" ]; then
    echo "官方网络配置缺少可读CA文件，停止请求" >&2
    exit 1
fi
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export HF_HOME="$project_root/runtime/cache/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
exec "$@"
