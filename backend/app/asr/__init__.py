"""语音转写层的组装入口：按配置选引擎（模式仿 retrieval 包）。

引擎选择只发生在**第一次调用**时（惰性单例）：`app.config` 在 import 期读
环境变量，但 ASR 引擎的构造要碰文件系统（找模型）甚至导入大依赖，
绝不能在模块导入期做——否则测试收集、健康检查都被拖下水。
测试用 `reset()` 换引擎。
"""
from __future__ import annotations

from .. import config
from .base import AsrResult, NullTranscriber, Transcriber

__all__ = ["AsrResult", "Transcriber", "NullTranscriber", "get_transcriber", "status", "reset"]

_transcriber: Transcriber | None = None


def get_transcriber() -> Transcriber:
    global _transcriber
    if _transcriber is None:
        engine = (config.ASR_ENGINE or "").strip().lower()
        if engine == "none":
            _transcriber = NullTranscriber("已在配置中显式关闭（ASR_ENGINE=none）")
        elif engine == "sherpa":
            from .sherpa_engine import SenseVoiceTranscriber

            _transcriber = SenseVoiceTranscriber(config.ASR_MODEL_DIR)
        else:
            _transcriber = NullTranscriber(
                f"未知引擎 ASR_ENGINE={engine!r}（可选：sherpa / none）"
            )
    return _transcriber


def status() -> dict:
    """给 /api/health 的 `asr` 块。只报事实，不触发模型加载。"""
    return get_transcriber().stats()


def reset() -> None:
    """丢弃单例。测试换配置后调用。"""
    global _transcriber
    _transcriber = None
