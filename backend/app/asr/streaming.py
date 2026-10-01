"""流式 ASR 引擎（二期）：sherpa-onnx 在线 Zipformer + WebSocket 边说边出字。

与一期批式（SenseVoice，整段收完再转）的分工：
- **流式**：延迟优先。边说边出字、按静音自动分段，供现场实时跟看；
  模型是流式 Zipformer bilingual（int8），CPU 实时率远低于 1。
- **批式**：质量优先（SenseVoice-small + ITN + 标点），`POST /api/asr/transcribe`
  保留给脚本与需要整段高精度转写的场景。UI 默认走流式。

模型**不入仓**（`data/asr-models/streaming-zipformer-bilingual-zh-en-2023-02-20/`，
已 gitignore），由 `scripts/fetch_asr_model.sh` 下载。没有模型时如实报
不可用，不做静默降级。

线程模型：识别器进程级单例（构造要读 ~190MB 权重，必须懒加载 + 复用）；
每次 WebSocket 连接各持一个 `OnlineStream`。sherpa 的 decode 非线程安全，
用锁串行化——现场只有一路收音，锁是防御性的。
"""
from __future__ import annotations

import threading
from pathlib import Path

from .. import config

#: 官方 release 的目录名（scripts/fetch_asr_model.sh 的落点）
STREAM_MODEL_DIRNAME = "streaming-zipformer-bilingual-zh-en-2023-02-20"

_lock = threading.Lock()
_recognizer = None  # sherpa_onnx.OnlineRecognizer

#: 解码锁：OnlineRecognizer 跨连接共享，decode_stream 非线程安全。
#: 没有这把锁，两个标签页/两个队友同时收音会在共享识别器上并发解码——
#: C++ 层状态损坏，症状难以归因（第四轮体检抓到"端点声称有锁、实际没拿"）。
decode_lock = threading.Lock()


def _locate() -> dict | None:
    """在 ASR_MODEL_DIR 下找流式模型三件套 + tokens。找不到返回 None。"""
    root = Path(config.ASR_MODEL_DIR)
    if not root.is_dir():
        return None
    candidates = [root / STREAM_MODEL_DIRNAME, *sorted(p for p in root.iterdir() if p.is_dir())]
    seen: set[Path] = set()
    for d in candidates:
        if d in seen:
            continue
        seen.add(d)
        encoders = sorted(d.glob("encoder-*.onnx"))
        decoders = sorted(d.glob("decoder-*.onnx"))
        joiners = sorted(d.glob("joiner-*.onnx"))
        tokens = d / "tokens.txt"
        # int8 优先：CPU 上更快，体积减半
        if tokens.is_file() and encoders and decoders and joiners:
            enc = next((p for p in encoders if "int8" in p.name), encoders[0])
            dec = next((p for p in decoders if "int8" in p.name), decoders[0])
            joi = next((p for p in joiners if "int8" in p.name), joiners[0])
            return {"encoder": enc, "decoder": dec, "joiner": joi, "tokens": tokens,
                    "dir": d}
    return None


def stream_available() -> bool:
    return _locate() is not None


def unavailable_reason() -> str:
    return (
        f"流式模型未下载：{config.ASR_MODEL_DIR} 下找不到 "
        f"{STREAM_MODEL_DIRNAME}（encoder/decoder/joiner int8 + tokens.txt）。"
        "先运行 bash scripts/fetch_asr_model.sh（一次性）"
    )


def get_recognizer():
    """进程级单例。模型加载推迟到第一个 WebSocket 连接，健康检查不触发它。"""
    global _recognizer
    if _recognizer is None:
        with _lock:
            if _recognizer is None:
                import sherpa_onnx

                loc = _locate()
                if loc is None:
                    raise RuntimeError(unavailable_reason())
                _recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                    tokens=str(loc["tokens"]),
                    encoder=str(loc["encoder"]),
                    decoder=str(loc["decoder"]),
                    joiner=str(loc["joiner"]),
                    num_threads=2,
                    sample_rate=16000,
                    feature_dim=80,
                    # 端点检测（官方默认三规则）：说完停顿 ~2.4s 自动切段，
                    # 长立论不会攒成一个巨型片段。
                    enable_endpoint_detection=True,
                    decoding_method="greedy_search",
                )
    return _recognizer


def reset() -> None:
    """丢弃单例（测试换模型目录后调用）。"""
    global _recognizer
    with _lock:
        _recognizer = None
