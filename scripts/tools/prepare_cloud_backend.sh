#!/usr/bin/env bash
# 仅部署服务依赖；既有重建环境、权重与Blender不修改。
set -euo pipefail
PROJECT_ROOT="${1:?需要云端项目根目录}"
CODE_ROOT="${2:?需要本轮代码目录}"
RUN_ROOT="${3:?需要本轮证据目录}"
SERVICE_PYTHON="$PROJECT_ROOT/runtime/envs/backend/bin/python"
PROBE_PYTHON="$PROJECT_ROOT/runtime/envs/probe/bin/python"
test -f "$CODE_ROOT/pyproject.toml"
test -x "$PROBE_PYTHON"
mkdir -p "$RUN_ROOT"
if [ ! -x "$SERVICE_PYTHON" ]; then
  test ! -e "$PROJECT_ROOT/runtime/envs/backend"
  "$PROBE_PYTHON" -m venv "$PROJECT_ROOT/runtime/envs/backend"
fi
if [ -e "$RUN_ROOT/dependencies-ready.json" ]; then
  echo '本轮依赖已经安装；先核对快照，不重复安装。'
  exit 0
fi
"$SERVICE_PYTHON" -m pip --disable-pip-version-check install --retries 0 --timeout 60 \
  -e "$CODE_ROOT[test,geometry,backend]" > "$RUN_ROOT/install.log" 2>&1
"$SERVICE_PYTHON" -m pip check > "$RUN_ROOT/pip-check.txt" 2>&1
"$SERVICE_PYTHON" -m pip freeze > "$RUN_ROOT/backend-linux.txt"
"$SERVICE_PYTHON" -c 'import sys,json,fastapi,langgraph,httpx,psutil,numpy,trimesh; print(json.dumps({"python":sys.version.split()[0],"framework_imports":True}))' > "$RUN_ROOT/dependencies-ready.json"
cat "$RUN_ROOT/dependencies-ready.json" "$RUN_ROOT/pip-check.txt"
