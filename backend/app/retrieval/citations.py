"""引用提取与回链核验。

为什么需要（交接文档「坑 3：幻觉引用」）：
法学辩论里编造"《XX法》第123条规定…"会直接导致 credibility 崩塌。
模型自己标"待核验"是靠自觉；这里做的是**程序化核对**：
把建议文本里的每条引用抽出来，拿去语料里查，给出确定的状态。

**两个正交的维度**：

1. **存在性**（`status`，三级，保守判定）
   - `verified`   已核验 —— 结构化语料里**确实有这一条**，且给出原文为证；
   - `dubious`    存疑   —— 该法存在但语料里找不到该条款（可能是编造，也可能是语料不全）；
                            或只在自由文本里出现（无法证明条款号与内容对应）；
   - `unverified` 未核验 —— 语料里根本没有这部法。

2. **内容一致性**（`claimed` / `match` / `content_ok`）
   条款号真实存在，不代表模型给它配的**条文内容**是对的。实测中模型写过
   "《著作权法》第十一条：…"这种真实条款号 + 编造内容（见 `docs/local-model-report.md`），
   旧版照样判 `verified`。现在把引用之后紧跟的那段"声称内容"抽出来，
   与语料原文做**最长公共子串重合度**比对，结果**并排展示**。

   注意这里**不改变 `status`** —— 重合度低只说明"模型的话与原文对不上"，
   有可能是编造，也有可能是合理的意译概括。系统只负责把证据摆出来，
   "这算不算问题"由人判断（与产品定位一致：AI 只出主意，决策权在人）。

**本模块是纯本地计算，不调用任何 LLM。**
"""
from __future__ import annotations

import difflib
import re
from typing import List, Optional, Tuple

from .base import MATCH_LOW, CitationCheck, CitationReport, Retriever

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

#: 抽取"声称内容"时用的终止符：句末与分号。逗号/顿号**不**作为终止符，
#: 因为法条内容本身常用逗号分层（"本法所称之作品，是指…"）。
_CLAIM_STOP = "。；;！!？?\n"
#: 声称内容的最大长度（超过就截断；太长的多半已经不是"引述"而是整段论证）
_CLAIM_MAX = 80
#: 声称内容的最小有效长度（归一化后）；太短的比不出名堂，不报
_CLAIM_MIN = 6

#: 引用与"声称内容"之间常见的连接噪声
_LEAD_JUNK_RE = re.compile(r"^[\s，,、：:—\-·的]+")
_LEAD_WORD_RE = re.compile(r"^(规定|明确|指出|载明|称|内容为|表述为|规定为|所规定)")
#: 归一化：只保留中日韩文字与字母数字（去标点、空白），避免标点差异干扰重合度
_KEEP_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]")


def _extract_matches(text: str) -> List[Tuple[int, int, str, str, str]]:
    """内部用：抽引用并**保留命中位置**（位置是内容比对的前提）。

    对外仍暴露 `extract()` 的三元组形状，不动既有调用方。
    """
    out: List[Tuple[int, int, str, str, str]] = []
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
        out.append((m.start(), m.end(), m.group(0), law, article))
    return out


def extract(text: str) -> List[tuple[str, str, str]]:
    """抽取引用，返回 [(原始串, 法名, 条款串)]，按法名+条款去重。"""
    return [(raw, law, art) for _, _, raw, law, art in _extract_matches(text)]


# --------------------------------------------------------------------------
# 内容一致性比对
# --------------------------------------------------------------------------
def _normalize(s: str) -> str:
    return _KEEP_RE.sub("", s or "")


def _claimed_after(text: str, pos: int) -> str:
    """抽取引用之后紧跟的"模型声称的规范内容"。

    典型形态：`《著作权法》第十一条规定：著作权属于作者。`
    → 剥掉"规定："这类连接噪声，在第一个句末符处截断，得到"著作权属于作者"。

    抽不出（后面直接换行/分号/没内容）就返回空串 —— **宁可不比对，也不硬凑**。
    """
    tail = (text or "")[pos : pos + _CLAIM_MAX + 40]
    if not tail:
        return ""
    tail = _LEAD_JUNK_RE.sub("", tail)
    tail = _LEAD_WORD_RE.sub("", tail)
    tail = _LEAD_JUNK_RE.sub("", tail)
    for i, ch in enumerate(tail):
        if ch in _CLAIM_STOP:
            tail = tail[:i]
            break
    claimed = tail.strip()
    return claimed if len(_normalize(claimed)) >= _CLAIM_MIN else ""


def _overlap(claimed: str, article: str) -> Optional[float]:
    """声称内容有多大比例能在语料原文里**连续**找到（0~1）。

    用「最长公共子串 / 声称内容长度」而不是整体相似度：法条原文通常比模型
    引述的那一句长得多，整体相似度会被长度差淹没；而"引述的原话能不能在原文里
    找到"才是我们要问的问题。意译概括会掉到阈值以下 —— 那是**给人看的信号**，
    不是自动判决（见模块头）。
    """
    a, b = _normalize(claimed), _normalize(article)
    if not a or not b:
        return None
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    block = matcher.find_longest_match(0, len(a), 0, len(b))
    return round(block.size / len(a), 3)


def verify_text(text: str, retriever: Retriever) -> CitationReport:
    """对一段文本里的所有引用做核验（存在性 + 内容一致性）。"""
    report = CitationReport(retriever=retriever.name)
    matches = _extract_matches(text)

    if not retriever.available:
        for _, _, raw, law, article in matches:
            report.items.append(CitationCheck(
                raw=raw, law=law, article=article,
                status="unverified", note=_NOTE_NO_CORPUS,
            ))
        report.total = len(report.items)
        report.unverified = report.total
        return report

    for _, end, raw, law, article in matches:
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
            # 存在性之外再比内容：条款真的存在，模型引述的内容也可能是编的。
            claimed = _claimed_after(text, end)
            if claimed:
                check.claimed = claimed
                check.match = _overlap(claimed, hit.text)
                if check.match is not None:
                    check.content_ok = check.match >= MATCH_LOW
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
    # 已核验里"引述与原文对不上"的条数：汇总行会单独提示，不混进上面三个计数
    report.content_suspect = sum(1 for i in report.items if i.content_ok is False)
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
