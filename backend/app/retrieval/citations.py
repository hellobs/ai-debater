"""引用提取与回链核验。

为什么需要（交接文档「坑 3：幻觉引用」）：
法学辩论里编造"《XX法》第123条规定…"会直接导致 credibility 崩塌。
模型自己标"待核验"是靠自觉；这里做的是**程序化核对**：
把建议文本里的每条引用抽出来，拿去语料里查，给出确定的状态。

三级状态（**保守判定**）：
- `verified`   已核验 —— 结构化语料里**确实有这一条**，且给出原文为证；
- `dubious`    存疑   —— 该法存在但语料里找不到该条款（可能是编造，也可能是语料不全）；
                        或只在自由文本里出现（无法证明条款号与内容对应）；
- `unverified` 未核验 —— 语料里根本没有这部法。

**本模块是纯本地计算，不调用任何 LLM。**
"""
from __future__ import annotations

import re
from typing import List

from .base import CitationCheck, CitationReport, Retriever

#: 《法名》[第X条][第X款]
CITATION_RE = re.compile(
    r"《([^》\n]{2,40}?)》"
    r"(?:第([零〇一二三四五六七八九十百千0-9]+)条)?"
    r"(?:第([零〇一二三四五六七八九十百千0-9]+)款)?"
)

_NOTE_NO_ARTICLE = "只引了法律名、没指明条款，无法核验具体内容"
_NOTE_ARTICLE_MISSING = "该法在语料中存在，但没有这一条——可能是编造，也可能是语料不全"
_NOTE_FREETEXT_ONLY = "仅在自由文本语料中命中，无法确认条款号与内容的对应关系"
_NOTE_LAW_MISSING = "语料中不存在这部法律"
_NOTE_NO_CORPUS = "未配置任何法源语料，无法核验"


def extract(text: str) -> List[tuple[str, str, str]]:
    """抽取引用，返回 [(原始串, 法名, 条款串)]，按法名+条款去重。"""
    out: List[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in CITATION_RE.finditer(text or ""):
        law = m.group(1).strip()
        article = ""
        if m.group(2):
            article = f"第{m.group(2)}条"
            if m.group(3):
                article += f"第{m.group(3)}款"
        key = (law, article)
        if key in seen:
            continue
        seen.add(key)
        out.append((m.group(0), law, article))
    return out


def verify_text(text: str, retriever: Retriever) -> CitationReport:
    """对一段文本里的所有引用做核验。"""
    report = CitationReport(retriever=retriever.name)
    citations = extract(text)

    if not retriever.available:
        for raw, law, article in citations:
            report.items.append(CitationCheck(
                raw=raw, law=law, article=article,
                status="unverified", note=_NOTE_NO_CORPUS,
            ))
        report.total = len(report.items)
        report.unverified = report.total
        return report

    for raw, law, article in citations:
        check = CitationCheck(raw=raw, law=law, article=article)
        law_known = _law_present(law, retriever)
        in_text = _in_freetext(raw, retriever)

        if not article:
            # 只引了法名：**无从核验具体内容**，不能算已核验。
            # （注意：不能用 lookup(law, "") 兜底——那会返回该法首条，造成假阳性。）
            if law_known or in_text:
                check.status = "dubious"
                check.note = _NOTE_NO_ARTICLE
                bare = retriever.lookup(law, "")
                if bare is not None:
                    check.origin = bare.origin
            else:
                check.status = "unverified"
                check.note = _NOTE_LAW_MISSING
            report.items.append(check)
            continue

        hit = retriever.lookup(law, article)
        if hit is not None:
            check.status = "verified"
            check.evidence = hit.text[:200]
            check.origin = hit.origin
        elif law_known:
            # 该法存在、但语料里没有这一条。
            # **不要把该法首条当"证据"显示**——那会看起来像在给这一条作证，属于误导。
            check.status = "dubious"
            check.note = _NOTE_ARTICLE_MISSING
            bare = retriever.lookup(law, "")
            if bare is not None:
                check.origin = bare.origin
        elif in_text:
            check.status = "dubious"
            check.note = _NOTE_FREETEXT_ONLY
        else:
            check.status = "unverified"
            check.note = _NOTE_LAW_MISSING

        report.items.append(check)

    report.total = len(report.items)
    report.verified = sum(1 for i in report.items if i.status == "verified")
    report.dubious = sum(1 for i in report.items if i.status == "dubious")
    report.unverified = sum(1 for i in report.items if i.status == "unverified")
    return report


def _law_present(law: str, retriever: Retriever) -> bool:
    """该法是否存在于结构化语料（或缺条款时能查到）。"""
    lookup = getattr(retriever, "law_exists", None)
    if callable(lookup):
        return bool(lookup(law))
    return retriever.lookup(law, "") is not None


def _in_freetext(raw: str, retriever: Retriever) -> bool:
    docs = getattr(retriever, "documents", [])
    return any(raw in text for _, text in docs)
