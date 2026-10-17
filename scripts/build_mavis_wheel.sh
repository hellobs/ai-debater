#!/usr/bin/env bash
#
# 重建 mavis 编译黑箱 wheel。
#
# ⚠️ 不需要 Visual Studio / Windows SDK / reg.exe —— 用 Nuitka 的 **zig 后端**。
#    首次会下载 Nuitka 与 zig 二进制（走 HTTP_PROXY / HTTPS_PROXY 环境变量）。
#
# 用法：
#   MAVIS_SRC=/path/to/mavis bash scripts/build_mavis_wheel.sh
#   MAVIS_SRC 默认 ../mavis（与 ai-debater 同级），即你本地能访问的 mavis 源码。
#   MAVIS_VERSION=1.3.3 可覆盖版本（须与 mavis 源码版本一致）。
#
# 产物：vendor/mavisframework-<version>-cp313-cp313-win_amd64.whl
#       （平台特定；其它平台/Python 请改 --tag 并在对应环境重跑。）
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAVIS_SRC="${MAVIS_SRC:-$(dirname "$ROOT")/mavis}"
OUT_DIR="${OUT_DIR:-$ROOT/vendor}"
VERSION="${MAVIS_VERSION:-1.3.3}"
PY="${PYTHON_BIN:-python3}"

[ -d "$MAVIS_SRC/mavisframework" ] || { echo "找不到 mavis 源码：$MAVIS_SRC"; exit 1; }

mkdir -p "$OUT_DIR"
BUILD="$ROOT/.mavis-build"
rm -rf "$BUILD"
mkdir -p "$BUILD/src"

# 拷贝源码到隔离构建区（保留 prompts / prompts_zh）
cp -r "$MAVIS_SRC/mavisframework" "$BUILD/src/mavisframework"
for f in pyproject.toml LICENSE README.md; do
  [ -f "$MAVIS_SRC/$f" ] && cp "$MAVIS_SRC/$f" "$BUILD/src/$f"
done

# 隔离构建 venv
"$PY" -m venv "$BUILD/venv"
if [ -x "$BUILD/venv/Scripts/pip.exe" ]; then
  VPY="$BUILD/venv/Scripts/python.exe"
elif [ -x "$BUILD/venv/bin/pip" ]; then
  VPY="$BUILD/venv/bin/python"
else
  echo "venv 创建失败"; exit 1
fi
"$VPY" -m pip install -q -U pip nuitka build

# 编译（zig 后端，跨平台、无需 VS/SDK）
cd "$BUILD/src"
"$VPY" -m nuitka --module --zig --assume-yes-for-downloads \
  --include-package=mavisframework --include-package-data=mavisframework \
  --output-dir=compiled mavisframework

# 打包 wheel
"$VPY" "$ROOT/scripts/build_mavis_wheel.py" \
  --mavis-src "$BUILD/src" --out-dir "$OUT_DIR" --version "$VERSION"

echo "完成：见 $OUT_DIR"
