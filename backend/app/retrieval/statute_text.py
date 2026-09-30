"""中文法律法规全文 → 结构化条款解析。

用途：把从「国家法律法规数据库」(flk.npc.gov.cn) 等来源下载的法律全文（纯文本/markdown），
切成 `{条款号: 正文}`，供 `LocalCorpusRetriever` 做**精确核验**（判「已核验」）。

**纯文本处理，不调用任何 LLM，也不内置任何法条内容。**
语料的准确性由来源文件负责——本模块只负责结构化，绝不"补全"或"纠正"条文。

切分依据（按可靠性排序）：

1. **行首锚定**是主判据。法条正文里的交叉引用（"依照本法第十一条的规定"）总在行中间，
   而条款起始必在行首 ⇒ 用 `^第X条` 锚定可把两者分开。
2. 章节标题（`第三章` / `第二节`）不切分，但要**从上一段正文尾部剥掉**，
   否则会混进上一条的条文里。
3. 页码残留（`- 3 -` / `— 12 —`）整行丢弃。

已知边界：若来源文本被硬换行成**一整行**（行首锚定找不到任何条款），
会抛出 `StatuteParseError`，要求先按行整理——不做有风险的兜底猜测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

__all__ = [
    "parse_statute_text", "guess_law_name", "int2cn", "article_no",
    "StatuteParseError", "ParseResult",
]

_CN_DIGITS = "零一二三四五六七八九"
_CN_NUM = "零〇一二三四五六七八九十百千两"
_NUM_PAT = f"[{_CN_NUM}0-9]+"

#: 行首的「第X条」——判据的核心
_LINE_ARTICLE = re.compile(rf"^[\s\u3000]*(第[\s\u3000]*({_NUM_PAT})[\s\u3000]*条)[\s\u3000]*")
#: 章节标题（不切分，需剥离）
_HEADING = re.compile(rf"^[\s\u3000]*第[\s\u3000]*{_NUM_PAT}[\s\u3000]*[章节](?:[\s\u3000]*.*)?$")
#: 整行页码残留
_PAGE_NO = re.compile(r"^[\s\u3000]*[-—－–~～\s]*\d{1,4}[-—－–~～\s]*$")
#: 标题行里常见的发布信息（用作法名识别的停止条件）
_LAW_SUFFIXES = ("法", "条例", "规定", "办法", "解释", "规则", "决定", "细则", "通则", "章程")


class StatuteParseError(ValueError):
    """文本无法按行首锚定切出条款。"""


@dataclass
class ParseResult:
    law: str
    articles: Dict[str, str] = field(default_factory=dict)
    #: 编号 1..max 中缺失的条款号（提示语料不全，不是错误）
    missing: List[int] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.articles)

    def summary(self) -> str:
        if not self.articles:
            return f"{self.law}：未解析出条款"
        nums = sorted(article_no(k) for k in self.articles)
        line = f"{self.law}：{self.count} 条（第{nums[0]}条 ~ 第{nums[-1]}条）"
        if self.missing:
            head = "、".join(f"第{n}条" for n in self.missing[:10])
            more = f" 等 {len(self.missing)} 处" if len(self.missing) > 10 else ""
            line += f"\n    缺号：{head}{more}"
        for w in self.warnings:
            line += f"\n    提示：{w}"
        return line


# ----------------------------------------------------------------------
def int2cn(n: int, _nested: bool = False) -> str:
    """整数 → 中文数字（覆盖法条序号范围；超出万级原样返回阿拉伯数字）。

    `_nested` 区分"独立成数"与"作为更高位的一部分"：法律文本写 **一百一十条**、
    而单独的 10 写作 **十条**。带高位时不能省那个"一"。
    """
    if n < 0:
        raise ValueError(n)
    if n >= 10000:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        tens = "一十" if _nested else "十"
        return tens + (_CN_DIGITS[n % 10] if n % 10 else "")
    if n < 100:
        return _CN_DIGITS[n // 10] + "十" + (_CN_DIGITS[n % 10] if n % 10 else "")
    for unit, size in (("千", 1000), ("百", 100)):
        if n >= size:
            head = _CN_DIGITS[n // size] + unit
            rest = n % size
            if rest == 0:
                return head
            if rest < size // 10:
                return head + "零" + int2cn(rest, True)   # 一百零五
            return head + int2cn(rest, True)
    return str(n)


def _cn2int(s: str) -> Optional[int]:
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000}
    total, number = 0, 0
    for ch in s:
        if ch in "零〇":
            continue
        if ch in digits:
            number = digits[ch]
        elif ch in units:
            total += (number or 1) * units[ch]
            number = 0
        else:
            return None
    return total + number


def article_no(key: str) -> int:
    """从 "第X条" 取出条号整数；认不出时返回一个大数（排序时沉底）。"""
    m = re.search(rf"第[\s\u3000]*({_NUM_PAT})[\s\u3000]*条", key)
    n = _cn2int(m.group(1)) if m else None
    return n if n is not None else 10 ** 6


# ----------------------------------------------------------------------
def _normalize(text: str) -> str:
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    # 图片型 OCR 常带出的零宽字符
    for ch in ("\u200b", "\u200e", "\u200f", "\ufeff"):
        text = text.replace(ch, "")
    return text


def guess_law_name(lines: List[str]) -> str:
    """从前几行猜法名：取第一条短行且以法律类后缀结尾者。"""
    for line in lines[:8]:
        s = line.strip().strip("#").strip()
        if not s or len(s) > 40:
            continue
        if s.endswith(_LAW_SUFFIXES) and "第" not in s[:2]:
            return s
    return ""


def _is_noise(line: str) -> bool:
    return bool(_PAGE_NO.match(line)) or _HEADING.match(line)


def _clean_lines(body: List[str]) -> List[str]:
    """剥掉尾部/首部的章节标题与页码残留，保留正文。

    章节标题夹在两条之间时，会同时留下空行 ⇒ 两者要一起循环剥离。
    """
    while body and (not body[-1].strip() or _is_noise(body[-1])):
        body.pop()
    while body and not body[0].strip():
        body.pop(0)
    return body


def parse_statute_text(text: str, law: str = "", *, min_articles: int = 3) -> ParseResult:
    """把法律全文切成 `{第X条: 正文}`。

    `law` 为空时从前几行猜法名；猜不到会给出 warning（调用方通常用文件名兜底）。
    """
    text = _normalize(text)
    lines = text.split("\n")

    starts: List[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = _LINE_ARTICLE.match(line)
        if m:
            starts.append((i, m.group(1), m.group(2)))

    if len(starts) < min_articles:
        raise StatuteParseError(
            f"行首锚定只找到 {len(starts)} 个「第X条」，少于 {min_articles} 个。"
            "可能原因：文本被硬换行成整段（请先按行整理），或该文件不是法律全文。"
        )

    law_name = law.strip() or guess_law_name(lines)
    result = ParseResult(law=law_name)
    if not law_name:
        result.warnings.append("未能从正文猜出法名，请用 --law 指定（否则核验时会对不上）")

    for idx, (line_i, raw, num) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        body_lines = _clean_lines(list(lines[line_i:end]))
        if not body_lines:
            continue
        # 首行去掉「第X条」标记本身，余下部分是条文开头
        body_lines[0] = _LINE_ARTICLE.sub("", body_lines[0], count=1)
        body = "".join(seg.strip() for seg in body_lines).strip()
        n = _cn2int(num)
        key = f"第{int2cn(n)}条" if n is not None else f"第{raw}条"
        if not body:
            result.warnings.append(f"{key} 正文为空，已跳过")
            continue
        if key in result.articles:
            # 同一文号在全文里出现多次（目录/索引里的简要说明会与正式条文重号），
            # 保留**更长**的正文：正式条文永远比目录摘要长，避免被后者覆盖成残条。
            if len(body) <= len(result.articles[key]):
                result.warnings.append(f"{key} 重复出现，保留较长正文（忽略较短的重复项）")
                continue
            result.warnings.append(f"{key} 重复出现，保留较长正文")
        result.articles[key] = body

    nums = sorted(article_no(k) for k in result.articles)
    if nums and nums[0] != 1:
        result.warnings.append(f"缺少第一条（从第{nums[0]}条开始），语料可能不完整")
    if nums:
        present = set(nums)
        result.missing = [n for n in range(1, nums[-1] + 1) if n not in present]

    return result
