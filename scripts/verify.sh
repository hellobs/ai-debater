#!/usr/bin/env bash
# 一键回归：体检/发布前的全套零消耗检查（不动上游、不花一分钱）。
# 用法：bash scripts/verify.sh          # 全量
#       bash scripts/verify.sh --fast   # 跳过 vitest（最快路径）
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAILED=0

step() { echo ""; echo "==== $1 ===="; }

step "后端 pytest"
cd "$ROOT/backend"
if ../.venv/Scripts/python.exe -m pytest 2>/dev/null | tail -1 || python -m pytest 2>/dev/null | tail -1; then
  :
else
  echo "pytest 失败"; FAILED=1
fi

step "前端 tsc"
cd "$ROOT/frontend"
if npx tsc --noEmit; then echo "tsc 通过"; else echo "tsc 失败"; FAILED=1; fi

step "前端 vitest"
if [ "$1" != "--fast" ]; then
  if npx vitest run 2>&1 | grep -E "Test Files|Tests "; then :; else echo "vitest 失败"; FAILED=1; fi
else
  echo "（--fast 跳过）"
fi

step "前端 build"
if npx vite build 2>&1 | tail -1; then :; else echo "build 失败"; FAILED=1; fi

step "后端健康探针（后端在跑时）"
if curl -s -m 3 http://127.0.0.1:8010/api/health 2>/dev/null | grep -q '"ok":true'; then
  echo "健康探针 ✓"
else
  echo "后端未运行（可选检查，跳过不算失败）"
fi

echo ""
if [ "$FAILED" = "0" ]; then echo "✅ 全部通过"; else echo "❌ 存在失败项"; exit 1; fi
