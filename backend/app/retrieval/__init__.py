"""检索层入口：按配置返回一个检索器。

当前只实现了本地语料检索（`LocalCorpusRetriever`）。
接入真实检索通道时，在这里加一个分支即可，业务代码不需要改。
"""
from __future__ import annotations

import logging
from pathlib import Path

from .. import config
from .base import (
    MATCH_LOW,
    RANK_ORDER,
    CitationCheck,
    CitationReport,
    LegalSource,
    NullRetriever,
    Retriever,
)
from .citations import extract, verify_text
from .local_corpus import LocalCorpusRetriever, cn2int, norm_article, norm_law

logger = logging.getLogger("retrieval")

_ROOTS = Path(__file__).resolve().parents[2]  # backend/
DEFAULT_CORPUS_DIR = str(_ROOTS.parent / "data" / "corpus")

_retriever: Retriever | None = None


def corpus_dir() -> Path:
    """语料目录的**唯一解析点**。空白值按未设置处理（走 config._env 同一防线），
    否则 `CORPUS_DIR=` 会把目录解析成当前目录，报错指向莫名其妙的地方。"""
    return Path(config._env("CORPUS_DIR", DEFAULT_CORPUS_DIR))


def get_retriever(force_reload: bool = False) -> Retriever:
    """惰性构建并复用检索器。"""
    global _retriever
    if _retriever is None or force_reload:
        d = corpus_dir()
        candidate = LocalCorpusRetriever(str(d))
        _retriever = candidate if candidate.available else NullRetriever()
        if not candidate.available:
            logger.info("未找到本地语料（%s），检索层退化为空实现", d)
    return _retriever


__all__ = [
    "MATCH_LOW",
    "RANK_ORDER",
    "CitationCheck",
    "CitationReport",
    "LegalSource",
    "NullRetriever",
    "Retriever",
    "LocalCorpusRetriever",
    "cn2int",
    "extract",
    "get_retriever",
    "norm_article",
    "norm_law",
    "verify_text",
]
