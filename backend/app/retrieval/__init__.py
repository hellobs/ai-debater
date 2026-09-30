"""检索层入口：按配置返回一个检索器。

当前只实现了本地语料检索（`LocalCorpusRetriever`）。
接入真实检索通道时，在这里加一个分支即可，业务代码不需要改。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

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


def get_retriever(force_reload: bool = False) -> Retriever:
    """惰性构建并复用检索器。"""
    global _retriever
    if _retriever is None or force_reload:
        corpus_dir = os.environ.get("CORPUS_DIR", DEFAULT_CORPUS_DIR)
        candidate = LocalCorpusRetriever(corpus_dir)
        _retriever = candidate if candidate.available else NullRetriever()
        if not candidate.available:
            logger.info("未找到本地语料（%s），检索层退化为空实现", corpus_dir)
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
