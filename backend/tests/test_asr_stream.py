"""流式 ASR（WebSocket /api/asr/stream）测试。

**全部 0 API 消耗**：识别是纯本地推理。默认（conftest 把 ASR_MODEL_DIR 指向
不存在的路径）只测「不可用态如实报原因」；真模型用例带 skipif——本机跑过
fetch_asr_model.sh 后自动生效，用 TTS 生成的中文样例走**完整 WebSocket 链路**
（config → 分帧 PCM → partial/segment → stop → final）。
"""
from __future__ import annotations

import wave
from pathlib import Path

import pytest

from app import config
from app.asr import streaming
from tests.conftest import TESTDATA

#: 仓库内真实模型目录（fetch_asr_model.sh 的落点）
REAL_MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "asr-models"
STREAM_SUBDIR = "streaming-zipformer-bilingual-zh-en-2023-02-20"
#: TTS 生成的中文样例（与批式测试共用；gitignore）
SAMPLE_WAV = TESTDATA / "asr-sample.wav"

has_stream_model = (
    REAL_MODEL_DIR / STREAM_SUBDIR / "encoder-epoch-99-avg-1.int8.onnx"
).exists()


def test_unavailable_reports_actionable_reason(client):
    """模型未下载：连接就被告知原因与下一步动作，绝不静默挂着。"""
    with client.websocket_connect("/api/asr/stream") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert "fetch_asr_model.sh" in msg["reason"]


@pytest.mark.skipif(not has_stream_model, reason="本机未下载流式模型")
def test_stream_speech_over_websocket(client, monkeypatch):
    """TTS 中文语音分帧灌入 → partial/segment → stop → final 命中关键词。"""
    monkeypatch.setattr(config, "ASR_MODEL_DIR", REAL_MODEL_DIR)
    streaming.reset()
    try:
        with client.websocket_connect("/api/asr/stream") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "config", "sample_rate": 16000})

            with wave.open(str(SAMPLE_WAV), "rb") as w:
                rate = w.getframerate()
                frames = w.readframes(w.getnframes())
            # ~100ms 一帧上送（3200B = 16000Hz × 2B × 0.1s），不模拟实时节奏
            step = rate * 2 // 10
            for i in range(0, len(frames), step):
                ws.send_bytes(frames[i : i + step])
            ws.send_json({"type": "stop"})

            segments: list[str] = []
            final: str | None = None
            for _ in range(20000):  # 防御性上限：协议失控时让测试失败而非挂死
                msg = ws.receive_json()
                if msg["type"] == "partial":
                    continue
                if msg["type"] == "segment":
                    segments.append(msg["text"])
                    continue
                if msg["type"] == "final":
                    final = msg["text"]
                    break
                pytest.fail(f"意外消息：{msg}")
            assert final is not None, "收到 stop 却没有 final 帧"
            # 别断言「著作权」三连字：流式 small 模型 + greedy 解码会有结巴式重复
            # （实测本样例转成「著著入作权」），这正是"流式管延迟、批式管质量"
            # 的取舍。断言核心内容词在文中出现即可，错字由人校对兜底。
            combined = "".join(segments) + final
            assert "保护" in combined and "成果" in combined
    finally:
        streaming.reset()  # 单例缓存着指向真实目录的识别器，别带进别的测试


@pytest.mark.skipif(not has_stream_model, reason="本机未下载流式模型")
def test_stream_silence_is_not_an_error(client, monkeypatch):
    """静音输入：协议正常走完（final 允许为空或填充词），不报错。"""
    monkeypatch.setattr(config, "ASR_MODEL_DIR", REAL_MODEL_DIR)
    streaming.reset()
    try:
        with client.websocket_connect("/api/asr/stream") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "config", "sample_rate": 16000})
            ws.send_bytes(b"\x00\x00" * 16000 * 2)  # 2s 数字静音
            ws.send_json({"type": "stop"})
            seen_final = False
            for _ in range(20000):
                msg = ws.receive_json()
                if msg["type"] == "final":
                    seen_final = True
                    break
                assert msg["type"] in ("partial", "segment")
            assert seen_final
    finally:
        streaming.reset()
