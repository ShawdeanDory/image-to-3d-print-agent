#!/usr/bin/env bash
# 密钥仅从已配置文本加载到进程环境，不回显；服务固定绑定回环地址。
set +x
set -euo pipefail
COMPONENT="${1:?请选择api或worker}"
PROJECT_ROOT="${2:-/root/autodl-tmp/image-to-3d-print-agent}"
SERVICE_PYTHON="$PROJECT_ROOT/runtime/envs/backend/bin/python"
export I3D_CONFIG="${I3D_CONFIG:-$PROJECT_ROOT/runtime/config/backend.json}"
CODE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# 运行本次明确部署的代码；模型子进程会单独清除PYTHONPATH。
export PYTHONPATH="$CODE_ROOT/src"
KEY_FILE="${I3D_LLM_KEY_FILE:-$PROJECT_ROOT/runtime/secrets/deepseek_api_key.txt}"
test -x "$SERVICE_PYTHON"
test -f "$I3D_CONFIG"
test -f "$KEY_FILE"
I3D_LLM_API_KEY="$(cat -- "$KEY_FILE")"
test -n "$I3D_LLM_API_KEY"
export I3D_LLM_API_KEY
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false
case "$COMPONENT" in
  api) exec "$SERVICE_PYTHON" -m image_to_3d_print.api ;;
  worker) exec "$SERVICE_PYTHON" -m image_to_3d_print.jobs.worker ;;
  *) echo '只支持api或worker' >&2; exit 2 ;;
esac
