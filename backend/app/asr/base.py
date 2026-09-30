"""语音转写层（ASR）：抽象接口 + 结果模型 + 音频工具。

阶段 7 一期取「批式」形态：前端在对方发言期间录一段单声道 PCM，一次性
POST 到 `/api/asr/transcribe`，返回纯文本。选型与理由见 docs/decision-log.md。

三条设计约束，别改回去：

1. 本层是**纯本地推理，不调用任何 LLM**，零 API 消耗、零网络依赖——
   现场网络不可靠是已知前提（HANDOVER 待确认项），语音输入不能依赖外网。
2. 转写结果只负责**填进可编辑的输入框**：识别错字由人在提交前校对。
   绝不自动触发参谋分析——「是否分析、以什么文本分析」的决策权归使用者，
   与整个产品「AI 只出主意，决策权在人」的定位一致。
3. 说话人区分用**手动分闸**（对方开口时开始收音、说完结束），不做说话人分离：
   现场只有两三个人说话，人手一按就能解决的事，不值得引入一套 diarization。
"""
from __future__ import annotations

import array
import sys
from dataclasses import dataclass
from typing import List, Optional


#: SenseVoice 是非流式模型：超长音频整体解码时内存与延迟都会劣化，
#: 按 30s 定长切窗逐段转写再拼接（按静音找切点的优化留给二期流式方案）。
CHUNK_SECONDS = 30


@dataclass
class AsrResult:
    """一次转写的结果。"""

    text: str                          # 转写文本（已去首尾空白；可能为空串）
    duration_s: float                  # 音频时长（秒）
    engine: str                        # 引擎名，如 sherpa-sensevoice
    latency_s: float                   # 本地转写耗时（秒）——现场可见的等待成本

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "duration_s": self.duration_s,
            "engine": self.engine,
            "latency_s": self.latency_s,
        }


class Transcriber:
    """转写器接口。接入新引擎时实现这个类即可（业务代码不动）。"""

    name = "base"
    available = False
    #: available=False 时给界面看的原因（如「模型未下载」），随 /api/health 下发
    unavailable_reason = ""
    #: 已加载的模型标识（用于健康检查展示）；未加载时为空串
    model_name = ""

    def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> AsrResult:
        """转写一段 16bit 小端单声道 PCM。返回 AsrResult，失败抛异常。"""
        raise NotImplementedError

    def stats(self) -> dict:
        """健康检查快照。不触发模型加载——加载只发生在第一次 transcribe。"""
        return {
            "engine": self.name,
            "available": self.available,
            "model": self.model_name or None,
            "reason": self.unavailable_reason or None,
        }


class NullTranscriber(Transcriber):
    """显式关闭（ASR_ENGINE=none）或引擎名不认识时的空实现。"""

    name = "none"

    def __init__(self, reason: str):
        self.unavailable_reason = reason

    def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> AsrResult:
        raise RuntimeError(self.unavailable_reason)


# --------------------------------------------------------------------------
# 音频工具（纯函数，独立可测）
# --------------------------------------------------------------------------
def pcm16_to_float32(pcm_bytes: bytes) -> List[float]:
    """16bit 小端 PCM → 归一化到 [-1, 1] 的浮点采样。

    sherpa-onnx 要求 [-1,1] 归一化的 1-D 序列；用 `array` 标准库解析，
    不为此引入 numpy（几百万采样点的一次性转换在亚秒量级，够用）。
    """
    samples = array.array("h")
    # 尾部不足 2 字节的残片（理论上不会出现）直接丢弃
    usable = len(pcm_bytes) - (len(pcm_bytes) % 2)
    samples.frombytes(pcm_bytes[:usable])
    if samples.itemsize != 2:  # pragma: no cover - array('h') 恒为 2 字节
        raise RuntimeError("array('h') 不是 16bit，当前平台的 C short 异常")
    # 字节序：frombytes 按**本机**字节序解释。音频流固定小端，
    # 大端平台上必须交换，否则整段音频变成噪声。
    if sys.byteorder == "big":
        samples.byteswap()
    return [s / 32768.0 for s in samples]


def split_chunks(samples: List[float], sample_rate: int) -> List[List[float]]:
    """按 CHUNK_SECONDS 定长切窗（最后一段可以不足）。"""
    step = max(1, int(CHUNK_SECONDS * sample_rate))
    return [samples[i:i + step] for i in range(0, len(samples), step)]
