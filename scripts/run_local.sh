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
# 默认 8B：4B 在「逻辑审计员」一路上实测系统性失效，8B 修好了它（docs/local-model-report.md §9）。
# 代价是慢约 5 倍；显存紧张要退回 4B 就跑：
#   OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M bash scripts/run_local.sh
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:8b}"

# --noproxy：本机端口不该走系统代理，否则会被代理拦成 10061
TAGS="$(curl -s --noproxy '*' --max-time 5 "$OLLAMA_HOST/api/tags" 2>/dev/null)"
if [ -z "$TAGS" ]; then
  printf '\033[31m[错误]\033[0m 连不上 Ollama：%s\n' "$OLLAMA_HOST"
  echo "       先启动服务：ollama serve"
  exit 1
fi

# 模型没拉过时，等来的会是一个看不懂的 404。这里直接说清该敲什么，省得去翻日志。
if ! printf '%s' "$TAGS" | grep -q "\"$OLLAMA_MODEL\""; then
  printf '\033[31m[错误]\033[0m 本机还没有模型 %s\n' "$OLLAMA_MODEL"
  echo "       拉一次即可：ollama pull $OLLAMA_MODEL"
  echo "       本机已有：$(printf '%s' "$TAGS" | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | paste -sd' ' -)"
  exit 1
fi

echo "==> 本地模型模式（0 API 消耗）"
echo "    模型   ：$OLLAMA_MODEL"
echo "    上游   ：$OLLAMA_HOST/v1"
echo "    协议桥 ：不参与"
echo "    注意   ：本地模型远慢于云端（8B 五路约 50s，4B 约 10s），见 docs/local-model-report.md §9"

# 关键一行：把 mavis 的 base_url 直接指向 Ollama，跳过协议桥。
export LLM_BRIDGE_URL="$OLLAMA_HOST/v1"
export LLM_MODEL="$OLLAMA_MODEL"
# 本地单实例推理，并发保守一些；接云端时可调到 ≥ 参谋路数
export LLM_CONCURRENCY="${LLM_CONCURRENCY:-2}"
# 8B 五路并行约 50s，而默认预算是 30s —— 照默认跑会有 3–4 路被判「超时」，
# 那不是模型不行，是预算太紧（实测见 local-model-report.md §9.2）。
# 本地模式没有"现场 30 秒"的压力，直接放宽到不至于误杀。
export ADVISOR_BUDGET_S="${ADVISOR_BUDGET_S:-120}"
# 内层（单次调用）必须比外层预算更宽，否则 mavis 会先超时并重试 ——
# 重试是真花钱的（本地不花钱，但会白等一轮 ×5s），答案还已经被判死了。
export LLM_TIMEOUT_S="${LLM_TIMEOUT_S:-180}"

cd "$ROOT/backend"
exec "$PY" -m app.main
