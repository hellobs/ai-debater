#!/usr/bin/env bash
#
# 下载语音转写模型（两套，均为 sherpa-onnx 官方发布、hf-mirror 直连）：
#   批式 SenseVoice-small int8（转写质量优先）+ 流式 Zipformer bilingual int8（边说边出字）。
# 共约 420MB；模型不入仓（data/asr-models/ 已 gitignore）。
#
# 为什么只拉两个文件而不下 GitHub release 的整包：整包 1.1GB（内含一份用不到的
# fp32 权重）；int8 是 CPU 推理该用的那份。默认走 hf-mirror.com（国内直连，
# 不需要代理）；要换源设 HF_ENDPOINT（如 https://huggingface.co）。
#
# 用法：
#   bash scripts/fetch_asr_model.sh
#
# 跑完不需要改任何代码：/api/health 的 asr.available（批式）与 asr.stream（流式）
# 会在对应文件就位后自动变 true。
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/data/asr-models"
REPO="${HF_ENDPOINT:-https://hf-mirror.com}/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main"

# 一期（批式）：SenseVoice-small int8
if [ ! -f "$DEST/model.int8.onnx" ] || [ ! -f "$DEST/tokens.txt" ]; then
  mkdir -p "$DEST"
  echo "==> 下载批式模型 int8 权重（约 228MB）← $REPO"
  curl -L --retry 3 --retry-delay 3 --progress-bar -o "$DEST/model.int8.onnx" "$REPO/model.int8.onnx"
  curl -L --retry 3 --retry-delay 3 -o "$DEST/tokens.txt" "$REPO/tokens.txt"
else
  echo "批式模型已存在：$DEST —— 跳过"
fi

# 二期（流式）：streaming zipformer bilingual int8（encoder/decoder/joiner + tokens）
STREAM_DIR="$DEST/streaming-zipformer-bilingual-zh-en-2023-02-20"
SREPO="${HF_ENDPOINT:-https://hf-mirror.com}/csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/resolve/main"
if [ -f "$STREAM_DIR/encoder-epoch-99-avg-1.int8.onnx" ] && [ -f "$STREAM_DIR/tokens.txt" ]; then
  echo "流式模型已存在：$STREAM_DIR —— 跳过"
else
  mkdir -p "$STREAM_DIR"
  echo "==> 下载流式模型 int8 三件套（约 190MB）← $SREPO"
  curl -L --retry 3 --retry-delay 3 --progress-bar -o "$STREAM_DIR/encoder-epoch-99-avg-1.int8.onnx" "$SREPO/encoder-epoch-99-avg-1.int8.onnx"
  curl -L --retry 3 --retry-delay 3 -o "$STREAM_DIR/decoder-epoch-99-avg-1.int8.onnx" "$SREPO/decoder-epoch-99-avg-1.int8.onnx"
  curl -L --retry 3 --retry-delay 3 -o "$STREAM_DIR/joiner-epoch-99-avg-1.int8.onnx" "$SREPO/joiner-epoch-99-avg-1.int8.onnx"
  curl -L --retry 3 --retry-delay 3 -o "$STREAM_DIR/tokens.txt" "$SREPO/tokens.txt"
fi

echo "==> 完成。重启后端（或点「重新检测」）即可看到 asr.available / asr.stream = true。"
