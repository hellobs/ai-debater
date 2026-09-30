#!/usr/bin/env bash
#
# 下载语音转写模型：sherpa-onnx 官方发布的 SenseVoice 中文包（int8 量化权重 +
# tokens），落到 data/asr-models/。一次性动作，约 228MB；模型不入仓（已 gitignore）。
#
# 为什么只拉两个文件而不下 GitHub release 的整包：整包 1.1GB（内含一份用不到的
# fp32 权重）；int8 是 CPU 推理该用的那份。默认走 hf-mirror.com（国内直连，
# 不需要代理）；要换源设 HF_ENDPOINT（如 https://huggingface.co）。
#
# 用法：
#   bash scripts/fetch_asr_model.sh
#
# 跑完不需要改任何代码：后端在 ASR_MODEL_DIR（默认 data/asr-models/）下找到
# model.int8.onnx + tokens.txt 即自动就绪，/api/health 的 asr.available 变 true。
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/data/asr-models"
REPO="${HF_ENDPOINT:-https://hf-mirror.com}/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main"

if [ -f "$DEST/model.int8.onnx" ] && [ -f "$DEST/tokens.txt" ]; then
  echo "模型已存在：$DEST —— 跳过下载"
  exit 0
fi

mkdir -p "$DEST"
echo "==> 下载 int8 权重（约 228MB）← $REPO"
curl -L --retry 3 --retry-delay 3 --progress-bar -o "$DEST/model.int8.onnx" "$REPO/model.int8.onnx"
echo "==> 下载 tokens"
curl -L --retry 3 --retry-delay 3 -o "$DEST/tokens.txt" "$REPO/tokens.txt"

echo "==> 完成。重启后端（或点「重新检测」）即可看到 asr.available=true。"
