"""语音转写层（ASR）测试。

**全部 0 API 消耗**：ASR 是纯本地推理，与上游模型无关。默认测试集把
ASR_MODEL_DIR 指向不存在的路径（conftest.py），测的是「引擎不可用时如实
报原因、绝不假装可用」——那是界面上唯一会发生的非正常态。

真正加载模型的那条测试带 skipif：本机跑过 scripts/fetch_asr_model.sh 且
存在 TTS 生成的样例音频时才执行，其他机器自动跳过（样例不入仓）。
"""
from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from app import asr as asr_mod
from app import config
from app.asr.base import pcm16_to_float32, split_chunks
from app.asr.sherpa_engine import SenseVoiceTranscriber
from tests.conftest import TESTDATA

#: 仓库内真实模型目录（fetch_asr_model.sh 的落点）；存在与否决定实测跳不跳
REAL_MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "asr-models"
#: TTS 生成的中文样例（验证环节用 PowerShell SAPI 生成，gitignore）
SAMPLE_WAV = TESTDATA / "asr-sample.wav"


def _find_int8_model(root: Path):
    """引擎同款查找规则：直接命中，或 release 整包解出的一级子目录。"""
    hits = sorted(root.glob("model.int8.onnx")) or sorted(root.glob("*/model.int8.onnx"))
    return hits[0] if hits else None


def _has_real_model(root: Path) -> bool:
    model = _find_int8_model(root)
    return model is not None and (model.parent / "tokens.txt").exists()


has_real_model = _has_real_model(REAL_MODEL_DIR)


# --------------------------------------------------------------------------
# 纯函数
# --------------------------------------------------------------------------
def test_pcm16_to_float32_normalizes_signed_range():
    raw = struct.pack("<3h", -16384, 0, 16384)
    assert pcm16_to_float32(raw) == [-0.5, 0.0, 0.5]


def test_pcm16_to_float32_drops_odd_tail():
    raw = struct.pack("<2h", 32767, -32768) + b"\x00"  # 尾部残片 1 字节
    out = pcm16_to_float32(raw)
    assert len(out) == 2 and out == [32767 / 32768.0, -1.0]


def test_locate_never_mixes_files_across_directories(tmp_path):
    """模型与 tokens 必须同目录配对，绝不跨目录混取（2026-10-01 实测缺陷）。

    场景：用户先后下载批式与流式模型后，data/asr-models/ 下出现流式子目录，
    其中也有 tokens.txt。旧实现"先扫子目录再扫根目录"会拿流式 tokens 配
    SenseVoice 模型，decode 时在 C++ 层抛 unordered_map 错误——且只有下载了
    流式模型后才会复现，极难归因。
    """
    from app.asr.sherpa_engine import SenseVoiceTranscriber

    # 根目录是完整的一对；子目录里埋一份同名 tokens 当"诱饵"
    (tmp_path / "model.int8.onnx").write_bytes(b"m")
    (tmp_path / "tokens.txt").write_text("batch", encoding="utf-8")
    sub = tmp_path / "streaming-sub"
    sub.mkdir()
    (sub / "tokens.txt").write_text("streaming", encoding="utf-8")

    loc = SenseVoiceTranscriber._locate(tmp_path)
    assert loc is not None
    assert loc["model"] == tmp_path / "model.int8.onnx"
    assert "batch" in loc["tokens"].read_text(encoding="utf-8")


def test_locate_falls_back_to_subdirectory_pair(tmp_path):
    """release 整包解压形态：根目录没有，一级子目录里成对出现 → 也能找到。"""
    from app.asr.sherpa_engine import SenseVoiceTranscriber

    sub = tmp_path / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    sub.mkdir()
    (sub / "model.int8.onnx").write_bytes(b"m")
    (sub / "tokens.txt").write_text("pair", encoding="utf-8")
    # 根目录只有孤儿 tokens（缺模型）→ 不得据此配对
    (tmp_path / "tokens.txt").write_text("orphan", encoding="utf-8")

    loc = SenseVoiceTranscriber._locate(tmp_path)
    assert loc is not None
    assert loc["model"].parent == sub
    assert "pair" in loc["tokens"].read_text(encoding="utf-8")


def test_split_chunks_keeps_short_tail():
    samples = list(range(10))
    chunks = split_chunks(samples, sample_rate=2)  # 30s * 2 = 每窗 60 点
    assert chunks == [samples]                     # 不足一窗 → 原样一段
    assert split_chunks(list(range(70)), sample_rate=1) == [
        list(range(30)), list(range(30, 60)), list(range(60, 70)),
    ]


# --------------------------------------------------------------------------
# 引擎选择与不可用态（模型目录被 conftest 指到不存在的测试路径）
# --------------------------------------------------------------------------
def test_unavailable_engine_states_the_reason():
    t = asr_mod.get_transcriber()
    assert t.available is False
    assert "模型未下载" in t.unavailable_reason
    assert "fetch_asr_model.sh" in t.unavailable_reason   # 给得出下一步动作


def test_health_carries_asr_block(client):
    block = client.get("/api/health").json()["asr"]
    assert block["available"] is False
    assert block["reason"]          # 原因必须能说到界面上


def test_transcribe_without_model_reports_reason(client):
    resp = client.post(
        "/api/asr/transcribe",
        content=struct.pack("<4h", 0, 0, 0, 0),
        headers={"X-Sample-Rate": "16000"},
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["ok"] is False and "模型" in data["error"]


def test_transcribe_rejects_empty_body(client):
    assert client.post("/api/asr/transcribe").status_code == 400


def test_transcribe_rejects_bad_sample_rate(client):
    resp = client.post(
        "/api/asr/transcribe", content=b"\x00\x00", headers={"X-Sample-Rate": "abc"}
    )
    assert resp.status_code == 400


def test_engine_none_disables_asr(client, monkeypatch):
    monkeypatch.setattr(config, "ASR_ENGINE", "none")
    asr_mod.reset()
    try:
        block = client.get("/api/health").json()["asr"]
        assert block["engine"] == "none" and block["available"] is False
        data = client.post(
            "/api/asr/transcribe", content=b"\x00\x00"
        ).json()
        assert data["ok"] is False and "关闭" in data["error"]
    finally:
        asr_mod.reset()  # 下一个测试拿回按 config 选出的引擎


# --------------------------------------------------------------------------
# 真模型实测（本机有模型 + 样例语音时才跑；0 网络依赖）
# --------------------------------------------------------------------------
@pytest.mark.skipif(not has_real_model, reason="本机未下载 SenseVoice 模型")
def test_real_engine_transcribes_speech(client, monkeypatch):
    engine = SenseVoiceTranscriber(REAL_MODEL_DIR)
    assert engine.available is True
    monkeypatch.setattr(asr_mod, "_transcriber", engine)

    with wave.open(str(SAMPLE_WAV), "rb") as w:
        rate, frames = w.getframerate(), w.readframes(w.getnframes())

    # 1) 端到端走 HTTP 端点：文本被转出来，且内容对得上（不是随机噪声）
    resp = client.post(
        "/api/asr/transcribe", content=frames, headers={"X-Sample-Rate": str(rate)}
    )
    data = resp.json()
    assert resp.status_code == 200 and data["ok"] is True
    assert data["duration_s"] > 0.5
    assert data["latency_s"] < data["duration_s"] * 2   # 现场等得起的硬要求
    assert "著作权" in data["text"], f"转写内容不符：{data['text']!r}"

    # 2) 静音输入：不报错即为过关。实测模型对全零段可能给出「嗯。」之类的
    #    填充词（数字静音≠模型认定的无声），所以只断言"是正常响应"，
    #    不承诺空文本——这类零碎由人在输入框里删。
    silence = b"\x00\x00" * (rate // 2)                  # 0.5s 静音
    silent = client.post(
        "/api/asr/transcribe", content=silence, headers={"X-Sample-Rate": "16000"}
    ).json()
    assert silent["ok"] is True and isinstance(silent["text"], str)
