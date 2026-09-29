"""与 mavis 的**唯一**接触面。

阶段 0 的实测结论（见 docs/spike-0-report.md）：
mavis 在本项目里只当**模型接入层**用——只借它的公开工厂 `create_llm_provider()`，
Agent / Simulator / 记忆都不用。所有业务逻辑留在本仓库，mavis 一行不改。

要换掉 mavis 时，只需要改这个文件。
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from . import config

logger = logging.getLogger("mavis_bridge")

_provider = None
_lock = threading.Lock()


def get_provider():
    """惰性创建并复用 provider（mavis 内部有全局并发信号量，复用即可）。"""
    global _provider
    if _provider is None:
        with _lock:
            if _provider is None:
                from mavisframework.runtime.llm import create_llm_provider

                _provider = create_llm_provider({
                    "provider": "openai",          # mavis 只会说 OpenAI 协议
                    "model": config.LLM_MODEL,
                    "base_url": config.LLM_BRIDGE_URL,   # 指向我们的协议桥
                    "api_key": "",                 # 桥不校验；上游凭据在桥进程环境变量里
                    "cache": False,
                    "concurrency": int(config.LLM_CONCURRENCY),
                })
                logger.info(
                    "mavis provider 就绪：model=%s base_url=%s",
                    config.LLM_MODEL, config.LLM_BRIDGE_URL,
                )
    return _provider


def complete(prompt: str, return_type=None, retry: int = 2) -> Any:
    """调用模型。`return_type` 为 pydantic 模型时走结构化输出。"""
    return get_provider().completion(prompt, retry=retry, return_type=return_type)


def stats() -> dict:
    p = get_provider()
    try:
        return p.get_summary()
    except Exception:  # noqa: BLE001
        return {}
