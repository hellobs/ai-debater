#!/usr/bin/env bash
#
# 本地模型模式（Ollama）—— **零 API 消耗**。
#
# 与默认模式的区别：
#   默认：后端 → 协议桥(8011) → Anthropic 协议网关（deepseek-chat，计费）
#   本模式：后端 → Ollama 的 OpenAI 兼容端点(11434/v1)（本地推理，不计费）
#
# ⇒ **本模式不需要启动协议桥。**
#   Ollama 的 /v1/chat/completions 实测支持 response_format=json_schema，
#   能返回严格 JSON 且顶层带 res，正好满足 mavis 的结构化输出要求。
#
# 用法：
#   bash scripts/run_local.sh
#   OLLAMA_MODEL=qwen3:8b LLM_CONCURRENCY=3 bash scripts/run_local.sh
#
# 前置：ollama serve 已启动，且模型已 pull。
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$ROOT/.venv}"
PY="${PYTHON_BIN:-$VENV/Scripts/python.exe}"
[ -x "$PY" ] || PY="$VENV/bin/python"

OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:4b-instruct-2507-q4_K_M}"

# --noproxy：本机端口不该走系统代理，否则会被代理拦成 10061
if ! curl -s --noproxy '*' --max-time 3 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  printf '\033[31m[错误]\033[0m 连不上 Ollama：%s\n' "$OLLAMA_HOST"
  echo "       先启动服务：ollama serve"
  exit 1
fi

echo "==> 本地模型模式（0 API 消耗）"
echo "    模型   ：$OLLAMA_MODEL"
echo "    上游   ：$OLLAMA_HOST/v1"
echo "    协议桥 ：不参与"
echo "    注意   ：本地 4B 模型在「逻辑审计员」一路上实测失效（见 docs/local-model-report.md）"

# 关键一行：把 mavis 的 base_url 直接指向 Ollama，跳过协议桥。
export LLM_BRIDGE_URL="$OLLAMA_HOST/v1"
export LLM_MODEL="$OLLAMA_MODEL"
# 本地单实例推理，并发保守一些；接云端时可调到 ≥ 参谋路数
export LLM_CONCURRENCY="${LLM_CONCURRENCY:-2}"

cd "$ROOT/backend"
exec "$PY" -m app.main
