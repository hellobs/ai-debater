#!/usr/bin/env bash
#
# 新机器从零准备环境。
#
# ⚠️ 本脚本只做三件事：装依赖、装 mavis、跑测试。
#    **它不会调用任何模型，不产生任何费用。**
#
# 用法：
#   bash scripts/bootstrap.sh
#
# 可用环境变量覆盖：
#   PYTHON_BIN    指定 python（默认 python3）
#   VENV          虚拟环境目录（默认 <仓库>/.venv）
#   MAVIS_DIR     mavis 本地目录（默认 <仓库>/../mavis，与仓库同级）
#   MAVIS_REPO    mavis 远端（默认官方 HTTPS 地址）
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV="${VENV:-$ROOT/.venv}"
MAVIS_DIR="${MAVIS_DIR:-$(dirname "$ROOT")/mavis}"
MAVIS_REPO="${MAVIS_REPO:-https://github.com/hellobs/mavis.git}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m[注意] %s\033[0m\n' "$1"; }

say "仓库根：$ROOT"

# ---------------------------------------------------------------------------
say "1/5 检查运行时"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 12), "需要 Python ≥ 3.12"'
echo "  Python: $("$PYTHON_BIN" -V)"
if command -v node >/dev/null 2>&1; then
  echo "  Node  : $(node -v)   （未找到也不影响跑后端测试）"
else
  warn "未找到 node —— 前端装不了，但协议桥/后端/测试都能正常跑。"
fi

# ---------------------------------------------------------------------------
say "2/5 准备 mavis（只读依赖，不改它）"
if [ -d "$MAVIS_DIR/.git" ]; then
  echo "  已存在：${MAVIS_DIR}（跳过 clone）"
else
  echo "  clone $MAVIS_REPO → $MAVIS_DIR"
  git clone --depth 1 "$MAVIS_REPO" "$MAVIS_DIR"
fi
echo "  版本：$(git -C "$MAVIS_DIR" describe --tags 2>/dev/null || git -C "$MAVIS_DIR" rev-parse --short HEAD)"
warn "mavis 只作为**只读依赖**安装；本项目的任何业务逻辑都不应写进 mavis。"

# ---------------------------------------------------------------------------
say "3/5 建虚拟环境并安装后端依赖"
if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV"
  echo "  已创建：$VENV"
else
  echo "  复用已有：$VENV"
fi
"$VENV/bin/pip" install -q -U pip
"$VENV/bin/pip" install -q "$MAVIS_DIR"
"$VENV/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
echo "  后端依赖安装完成"

# ---------------------------------------------------------------------------
say "4/5 安装前端依赖"
if command -v node >/dev/null 2>&1; then
  cd "$ROOT/frontend"
  if [ -d node_modules/vite ]; then
    echo "  已存在，跳过（幂等）"
  # 正常机器直接装即可；某些受限环境不允许创建 node_modules/.bin，
  # 那时 npm 会整体中断（且退出码仍为 0，很隐蔽），退回 --no-bin-links。
  # 注意只删 node_modules，**不动已提交的 package-lock.json**。
  elif npm install --no-audit --no-fund >/dev/null 2>&1 && [ -d node_modules/vite ]; then
    echo "  前端依赖安装完成（npm run dev / npm run build 可用）"
  else
    warn "常规安装失败，改用 --no-bin-links 重试（受限环境常见）"
    rm -rf node_modules
    npm install --no-audit --no-fund --no-bin-links >/dev/null 2>&1 || true
    if [ -d node_modules/vite ]; then
      echo "  已装好，但没有 node_modules/.bin"
      echo "  ⇒ 本机请用：node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173"
      echo "  ⇒ 构建请用：node node_modules/vite/bin/vite.js build"
    else
      warn "前端依赖仍安装失败，请手动检查网络与 npm 配置。后端不受影响。"
    fi
  fi
  cd "$ROOT"
else
  echo "  跳过（没有 node）"
fi

# ---------------------------------------------------------------------------
say "5/5 跑测试（全部本地计算，0 API 消耗）"
cd "$ROOT/backend"
"$VENV/bin/python" -m pytest

# ---------------------------------------------------------------------------
cat <<EOF

==> 准备完成。下一步：

  1) 配置凭据（**只走环境变量，不要写进任何文件**）：
       export ANTHROPIC_BASE_URL=...        # 注意：换台电脑可能对应另一个账户
       export ANTHROPIC_AUTH_TOKEN=...
       export LLM_MODEL=deepseek-chat       # 可选，默认就是这个

  2) 起三个服务（三个终端）：
       # 协议桥
       cd backend && LLM_BRIDGE_PORT=8011 "$VENV/bin/python" -m app.llm_bridge
       # 后端
       cd backend && "$VENV/bin/python" -m app.main
       # 前端（见上，受限环境下用 node 直跑 vite）

  3) 自检（0 消耗）：
       curl -s http://127.0.0.1:8011/healthz
       curl -s http://127.0.0.1:8010/api/health

  ⚠️ 点一次「生成参谋建议」= 5 次上游调用；超时也计费。
     任何会产生真实消耗的测试，先确认清楚再用。
     详见 HANDOVER.md 的「成本红线」一节。

  4) 想让引用核验能判「已核验」：
     把法条全文放进 data/corpus/（格式见该目录 README），零代码改动。

EOF
