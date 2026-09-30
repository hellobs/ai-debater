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
#   PYTHON_BIN    指定 python（默认自动找 python3 → python）
#   VENV          虚拟环境目录（默认 <仓库>/.venv）
#   MAVIS_DIR     mavis 本地目录（默认 <仓库>/../mavis，与仓库同级）
#   MAVIS_REPO    mavis 远端（默认官方 HTTPS 地址）
#
# 平台支持：Linux / macOS / **Windows（Git Bash）**。两条平台差异在这里处理：
#   1. 虚拟环境的可执行目录：POSIX 是 `bin/`，Windows 是 `Scripts/`；
#   2. 默认解释器名：Windows 上常常只有 `python`，没有 `python3`。
# 这两处原先都硬编码成 `$VENV/bin/python`，Windows 上会在第 3 步直接断
# —— 而本脚本正是 README「一键引导」指向的入口，第一个动作就失败最伤。
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$ROOT/.venv}"
MAVIS_DIR="${MAVIS_DIR:-$(dirname "$ROOT")/mavis}"
MAVIS_REPO="${MAVIS_REPO:-https://github.com/hellobs/mavis.git}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m[注意] %s\033[0m\n' "$1"; }

say "仓库根：$ROOT"

# ---------------------------------------------------------------------------
say "1/5 检查运行时"

# 默认解释器：Windows 上 `python3` 经常不存在，而 `python` 在。两个都找。
PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then
  printf '\033[31m[错误]\033[0m 找不到 python3 或 python，请用 PYTHON_BIN=... 指定\n' >&2
  exit 1
fi

"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 12), "需要 Python >= 3.12"'
echo "  Python: $("$PYTHON_BIN" -V)  （来自 $PYTHON_BIN）"
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

# 已存在的 venv 两种布局都认（POSIX 的 bin/ 与 Windows 的 Scripts/）。
if [ -x "$VENV/bin/python" ] || [ -x "$VENV/Scripts/python.exe" ]; then
  echo "  复用已有：$VENV"
else
  "$PYTHON_BIN" -m venv "$VENV"
  echo "  已创建：$VENV"
fi

# 解析出这个 venv 的可执行目录与解释器。
if [ -x "$VENV/Scripts/python.exe" ]; then
  VBIN="$VENV/Scripts"
  VPY="$VBIN/python.exe"
else
  VBIN="$VENV/bin"
  VPY="$VBIN/python"
fi
if [ ! -x "$VPY" ]; then
  printf '\033[31m[错误]\033[0m venv 建好了但找不到解释器：%s\n' "$VPY" >&2
  echo "       请删掉 $VENV 后重跑本脚本。" >&2
  exit 1
fi
echo "  venv 可执行目录：$VBIN"

# 一律走 `python -m pip`：不依赖 pip 的可执行 shim
# （某些受限环境下 bin/ 或 Scripts/ 里的 shim 建不出来）。
"$VPY" -m pip install -q -U pip
"$VPY" -m pip install -q "$MAVIS_DIR"
"$VPY" -m pip install -q -r "$ROOT/backend/requirements.txt"
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
"$VPY" -m pytest

# ---------------------------------------------------------------------------
cat <<EOF

==> 准备完成。下一步：

  1) 配置凭据（二选一，**绝不写进任何入仓文件**）：
       a) 写进 <仓库>/.env（该文件已在 .gitignore 中排除）：
            cp .env.example .env   # 然后填写 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN
          注意：.env 里的**空白值会被当成"未设置"**，留空项走默认，不会顶掉默认值。
       b) 或直接 export（优先级高于 .env）：
            export ANTHROPIC_BASE_URL=...
            export ANTHROPIC_AUTH_TOKEN=...
            export LLM_MODEL=deepseek-chat       # 可选，默认就是这个

  2) 起三个服务（三个终端）。用绝对路径 —— 下面几条会 cd，相对路径到那步就不对了：
       PY="$VPY"
       cd backend && LLM_BRIDGE_PORT=8011 "\$PY" -m app.llm_bridge   # 协议桥（必须最先起）
       cd backend && "\$PY" -m app.main                              # 后端 :8010
       cd frontend && npm run dev                                    # 前端 :5173

  3) 自检（0 消耗）：
       curl -s --noproxy '*' http://127.0.0.1:8011/healthz
       curl -s --noproxy '*' http://127.0.0.1:8010/api/health

  ⚠️ 点一次「生成参谋建议」= 5 次上游调用；超时也计费。
     任何会产生真实消耗的测试，先确认清楚再用。
     详见 HANDOVER.md 的「成本红线」一节。

  4) 想让引用核验能判「已核验」：
     把法条全文放进 data/corpus/（格式见该目录 README），零代码改动。

  5) 接手前必读（按此顺序）：
     HANDOVER.md → docs/decision-log.md → docs/mavis-gap-report.md

EOF
