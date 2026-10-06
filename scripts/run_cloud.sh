#!/usr/bin/env bash
#
# 云端模式（**计费**）：后端 → 进程内协议桥 → Anthropic 协议网关（如 DeepSeek）。
#
# 与 `run_local.sh` 的关系：两个模式各自把 `LLM_BRIDGE_URL` 指到不同地方，
# 其余（预算、并发、超时）都留在各自脚本里 —— 因为这两组值在两种模式下的
# 合理取值是相反的（本地要放宽，云端要收紧）。
#
# 协议桥**不用单独起**：`llm_bridge` 已 mount 进后端进程（见 app/main.py），
# 上游形态为 anthropic 时 mavis 自动指向 `http://127.0.0.1:<API_PORT>/bridge/v1`。
#
# 用法：
#   bash scripts/run_cloud.sh
#   ADVISOR_BUDGET_S=45 bash scripts/run_cloud.sh     # 现场网络慢时放宽预算
#
# 前置：仓库根的 `.env` 里有 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN
#       （密钥绝不要写进任何入仓文件，见 .gitignore）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$ROOT/.venv}"
PY="${PYTHON_BIN:-$VENV/Scripts/python.exe}"
[ -x "$PY" ] || PY="$VENV/bin/python"

API_PORT="${API_PORT:-8010}"
WEB_PORT="${WEB_PORT:-5173}"

if [ ! -f "$ROOT/.env" ]; then
  echo "✗ 找不到 $ROOT/.env —— 云端模式的地址与密钥都从它读。" >&2
  echo "  照 .env.example 复制一份，填 ANTHROPIC_BASE_URL 与 ANTHROPIC_AUTH_TOKEN。" >&2
  exit 1
fi

cd "$ROOT/backend"
# 从 .env 读初值打印（**只打印主机与模型**：密钥一个字都不出）。
"$PY" - <<'PYEOF'
import os, pathlib, sys
sys.path.insert(0, os.getcwd())
from app import config

base, key = config._env("ANTHROPIC_BASE_URL"), config._env("ANTHROPIC_AUTH_TOKEN")
if not base or not key:
    print("✗ .env 里缺 ANTHROPIC_BASE_URL 或 ANTHROPIC_AUTH_TOKEN。", file=sys.stderr)
    raise SystemExit(1)
print("==> 云端模式（每次点「分析」= 5 次上游调用，超时也计费）")
print(f"    上游   ：{base}")
print(f"    模型   ：{config.LLM_MODEL}")
print(f"    预算   ：{config.ADVISOR_BUDGET_S}s / 路，并发 {config.LLM_CONCURRENCY}")
print(f"    密钥   ：已配置（长度 {len(key)}，不显示）")
PYEOF

# 前端：已在监听就不重复起（vite 端口占用会自己换端口，容易让人以为出怪事）
if ! netstat -ano 2>/dev/null | grep -q "127.0.0.1:$WEB_PORT .*LISTENING"; then
  if [ -d "$ROOT/frontend/node_modules" ]; then
    echo "==> 起前端：http://127.0.0.1:$WEB_PORT"
    # 日志落在 .workbuddy/ 下：那个目录不入仓，写在仓库里会变成一堆未跟踪文件
    LOG_DIR="$ROOT/.workbuddy/logs"; mkdir -p "$LOG_DIR"
    ( cd "$ROOT/frontend" && node node_modules/vite/bin/vite.js \
        --host 127.0.0.1 --port "$WEB_PORT" >"$LOG_DIR/vite.log" 2>&1 & )
    sleep 2
  else
    echo "! 前端依赖没装（frontend/node_modules 不存在），只起后端。" >&2
  fi
fi

echo "==> 后端：http://127.0.0.1:$API_PORT （Ctrl-C 停止）"
exec "$PY" -m app.main
