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
#   VENDOR_WHEEL  mavis 预编译黑箱 wheel（默认 <仓库>/vendor/mavisframework-*.whl）
#
# mavis 是**编译黑箱**分发：仓库 vendor/ 下附带一个平台特定的 .whl，
# 内含原生 .pyd（无明文源码）+ 随附的 prompts 模板。无需联网拉 mavis 源码，
# 也无需能访问 GitHub。其它平台/Python 版本请按 docs 重建对应 wheel。
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
#: mavis 版本钉死在 wheel 文件名里（当前 1.3.3）。换版本须同步重建 wheel，
#: 见脚本末尾注释 / 构建文档。本项目对 mavis 的探针是按内部签名打桩的，
#: 版本不能随意跟随默认分支。
VENDOR_WHEEL="${VENDOR_WHEEL:-$ROOT/vendor/mavisframework-1.3.3-cp313-cp313-win_amd64.whl}"

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
say "2/5 准备 mavis（编译黑箱 wheel，已随仓库附带）"
if [ -f "$VENDOR_WHEEL" ]; then
  echo "  预编译 wheel：$(basename "$VENDOR_WHEEL")"
else
  warn "未找到预编译 wheel：$VENDOR_WHEEL"
  warn "mavis 已改为编译黑箱分发，**不再从 GitHub 拉源码**。请改用对应平台的 wheel，"
  warn "或按文档重新构建（见 bootstrap.sh 末尾注释）。"
  exit 1
fi
echo "  ⓘ 实际安装放在第 3 步（建好 venv 之后）。"
warn "mavis 只作为**只读黑箱依赖**安装；本项目的任何业务逻辑都不应写进 mavis。"

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
# mavis 编译黑箱 wheel：已装则跳过（幂等），否则从 vendor/ 安装。
if "$VPY" -c 'import mavisframework' >/dev/null 2>&1; then
  echo "  mavis 已安装（$( "$VPY" -c 'import mavisframework; print(mavisframework.__version__)' 2>/dev/null || echo '?' )），跳过"
else
  "$VPY" -m pip install -q "$VENDOR_WHEEL"
  echo "  已从 wheel 安装 mavis $( "$VPY" -c 'import mavisframework; print(mavisframework.__version__)' )"
fi
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
            export LLM_MODEL=deepseek-flash       # 可选，默认就是 deepseek-flash

  2) 起服务（两个终端）。协议桥已挂载进后端进程（/bridge/v1），**不必单独起桥**：
       PY="$VPY"
       cd backend && "\$PY" -m app.main            # 后端 :8010（含协议桥）
       cd frontend && npm run dev                 # 前端 :5173
      # 若要用独立桥（:8011）模式：先 `LLM_BRIDGE_PORT=8011 "$PY" -m app.llm_bridge`，
      # 并额外 export LLM_BRIDGE_URL=http://127.0.0.1:8011/v1 让 mavis 指向它。

  3) 自检（0 消耗）：
       curl -s --noproxy '*' http://127.0.0.1:8010/bridge/healthz
       curl -s --noproxy '*' http://127.0.0.1:8010/api/health

  ⚠️ 点一次「生成参谋建议」= 5 次上游调用；超时也计费。
     任何会产生真实消耗的测试，先确认清楚再用。
     详见 HANDOVER.md 的「成本红线」一节。

  4) 想让引用核验能判「已核验」：
     把法条全文放进 data/corpus/（格式见该目录 README），零代码改动。

  5) 接手前必读（按此顺序）：
     HANDOVER.md → docs/decision-log.md → docs/mavis-gap-report.md

EOF
