"""本地 ASR 引擎：sherpa-onnx + SenseVoice（一期选型，理由见 docs/decision-log.md）。

为什么是它而不是 Whisper：中文语料上 SenseVoice-small 的准确率优于同尺寸
Whisper 且 CPU 推理快一个量级（int8 下 RTF 约 0.03–0.1，30s 音频约 1–2s 出文），
符合「现场等得起」的预算；sherpa-onnx 是单个自包含 wheel（无 torch），
Python 3.13 的 Windows 轮子已实测可用。

模型**不入仓**（data/asr-models/ 已 gitignore）：由 scripts/fetch_asr_model.sh
从 sherpa-onnx 官方 release 下载解压。没有模型时本引擎如实报 unavailable，
绝不假装可用。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .base import AsrResult, Transcriber, pcm16_to_float32, split_chunks

#: 模型文件名（官方 release 的固定命名；int8 优先，体积减半、CPU 上更快）
_MODEL_GLOBS = ("model.int8.onnx", "model.onnx")
_TOKENS = "tokens.txt"


class SenseVoiceTranscriber(Transcriber):
    name = "sherpa-sensevoice"

    def __init__(self, model_dir: Path):
        # 依赖检查放构造期： sherpa-onnx 装没装是环境事实，当场定性，
        # 别等到第一次点收音才在 transcribe 里炸出一个 ImportError。
        try:
            import sherpa_onnx  # noqa: F401
            lib_err = ""
        except Exception as exc:  # noqa: BLE001 —— 任何导入失败都要给得出原因
            lib_err = f"sherpa-onnx 未安装或导入失败：{exc}"

        self._model_path = self._locate(model_dir, _MODEL_GLOBS)
        self._tokens_path = self._locate(model_dir, (_TOKENS,))

        if lib_err:
            self.unavailable_reason = lib_err
        elif self._model_path is None or self._tokens_path is None:
            self.unavailable_reason = (
                f"模型未下载：{model_dir} 下找不到 {_MODEL_GLOBS[0]} 与 {_TOKENS}。"
                "先运行 bash scripts/fetch_asr_model.sh（约 230MB，一次性）"
            )
        else:
            self.model_name = self._model_path.parent.name
            self.available = True

        self._recognizer = None
        # OfflineRecognizer 不是线程安全的；现场只有一路转写在跑，
        # 加锁是防御性的（防止连点两次收音产生并发解码）。
        self._lock = threading.Lock()

    @staticmethod
    def _locate(model_dir: Path, names: tuple[str, ...]) -> Path | None:
        """在模型目录（含一级子目录）里找文件。release 解压后带一层目录名。"""
        base = Path(model_dir)
        if not base.is_dir():
            return None
        for name in names:
            hits = sorted(base.glob(f"*/{name}")) or sorted(base.glob(name))
            if hits:
                return hits[0]
        return None

    def _ensure_loaded(self) -> None:
        """模型加载推迟到第一次转写——构造期/健康检查都不该吃这份内存与秒数。"""
        if self._recognizer is not None:
            return
        import sherpa_onnx

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(self._model_path),
            tokens=str(self._tokens_path),
            num_threads=2,
            use_itn=True,      # 数字口语 → 书面（「二零二四」→「2024」），参谋吃文本
            language="",       # 空串 = 自动判语种（中英混合是辩论现场常态）
        )

    def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> AsrResult:
        if not self.available:
            raise RuntimeError(self.unavailable_reason)
        started = time.perf_counter()
        samples = pcm16_to_float32(pcm_bytes)
        duration = len(samples) / float(sample_rate) if sample_rate else 0.0
        texts: list[str] = []
        with self._lock:
            self._ensure_loaded()
            # 非流式模型按窗解码；sample_rate 不符时 sherpa-onnx 内部重采样
            for chunk in split_chunks(samples, sample_rate):
                if not chunk:
                    continue
                stream = self._recognizer.create_stream()
                stream.accept_waveform(sample_rate, chunk)
                self._recognizer.decode_stream(stream)
                piece = stream.result.text.strip()
                if piece:
                    texts.append(piece)
        latency = time.perf_counter() - started
        return AsrResult(
            text="".join(texts),
            duration_s=round(duration, 2),
            engine=self.name,
            latency_s=round(latency, 2),
        )
