"""检索层：抽象接口 + 检索结果模型。

设计前提：**检索通道尚未确定**（用户明确"先不管检索"）。
所以这一层只定义抽象与本地实现，不绑定任何外部服务：
- 有本地语料 → `LocalCorpusRetriever` 立即可用；
- 接入真实检索（搜索 API / 连接器）→ 新增一个 `Retriever` 子类，其余代码不动。

注意：本层是**纯本地计算，不调用任何 LLM**，零 API 消耗。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

#: 法源效力位阶（由高到低）。用于防止"把学说当法条"——交接文档明确点名的常见错误。
RANK_ORDER = [
    "宪法",
    "法律",
    "司法解释",
    "行政法规",
    "地方性法规",
    "指导性案例",
    "公报案例",
    "类案",
    "学说",
    "教科书",
]


@dataclass
class LegalSource:
    """一条法源。"""

    source_type: str = "法律"          # 法律 / 司法解释 / 判例 / 学说 ...
    law: str = ""                      # 《中华人民共和国著作权法》
    article: str = ""                  # 第三条 / 第十一条第三款
    text: str = ""                     # 原文（可能被截断）
    origin: str = ""                   # 出处：文件路径 / URL
    rank: int = 99                     # 效力位阶，越小越高；由 source_type 推导

    def __post_init__(self) -> None:
        for i, name in enumerate(RANK_ORDER):
            if self.source_type == name or name in self.source_type:
                self.rank = i
                break

    @property
    def citation(self) -> str:
        base = self.law or ""
        return f"{base}{self.article}" if self.article else base

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "law": self.law,
            "article": self.article,
            "citation": self.citation,
            "text": self.text[:300],
            "origin": self.origin,
            "rank": self.rank,
        }


@dataclass
class CitationCheck:
    """一条引用的核验结果。"""

    raw: str                           # 原文里出现的引用串
    law: str                           # 提取出的法律名
    article: str = ""                  # 提取出的条款
    status: str = "unverified"         # verified | dubious | unverified
    evidence: str = ""                 # 命中时的原文片段
    origin: str = ""                   # 出处
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "law": self.law,
            "article": self.article,
            "status": self.status,
            "evidence": self.evidence,
            "origin": self.origin,
            "note": self.note,
        }


class Retriever:
    """检索器接口。接入新通道时实现这个类即可。"""

    name = "base"
    available = False

    def search(self, query: str, k: int = 5) -> List[LegalSource]:
        raise NotImplementedError

    def lookup(self, law: str, article: str = "") -> Optional[LegalSource]:
        """精确查条款（引用核验用）。"""
        return None

    def stats(self) -> dict:
        return {"name": self.name, "available": self.available}


class NullRetriever(Retriever):
    """没有语料时的空实现：一切查询返回空，引用一律标 unverified。"""

    name = "null"
    available = False


@dataclass
class CitationReport:
    """一次核验的汇总。"""

    total: int = 0
    verified: int = 0
    dubious: int = 0
    unverified: int = 0
    items: List[CitationCheck] = field(default_factory=list)
    retriever: str = "null"

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "verified": self.verified,
            "dubious": self.dubious,
            "unverified": self.unverified,
            "retriever": self.retriever,
            "items": [i.to_dict() for i in self.items],
        }
