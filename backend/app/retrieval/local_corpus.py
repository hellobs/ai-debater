"""本地语料检索器。

语料目录：`data/corpus/`（可用环境变量 `CORPUS_DIR` 覆盖）

支持两种文件：
1. `*.json` —— 结构化法条，用于**精确核验**。两种写法都接受：

   ```json
   { "《中华人民共和国著作权法》": { "第三条": "本法所称的作品，是指…" } }
   ```
   ```json
   [ { "law": "《著作权法》", "article": "第三条", "text": "…" } ]
   ```

2. `*.md` / `*.txt` —— 自由文本（判例集、学说摘录等），用于**模糊检索**与兜底核验。
   自由文本只能判到"存疑"：它无法证明条款号与内容的对应关系。

本模块是**纯本地计算，不调用任何 LLM**。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import LegalSource, Retriever

logger = logging.getLogger("retrieval")

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100, "千": 1000,
}


def cn2int(s: str) -> Optional[int]:
    """中文数字 → 整数（支持到千位，足够覆盖法条序号）。阿拉伯数字原样返回。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total = 0
    number = 0
    for ch in s:
        if ch in "零〇":
            continue
        v = _CN_DIGITS.get(ch)
        if v is None:
            return None
        if v >= 10:
            total += (number or 1) * v
            number = 0
        else:
            number = v
    return total + number


def norm_law(name: str) -> str:
    """法律名归一：去书名号、去空白、去"中华人民共和国"前缀。"""
    n = (name or "").strip()
    n = n.strip("《》〈〉 ")
    n = re.sub(r"\s+", "", n)
    return n.replace("中华人民共和国", "")


def norm_article(article: str) -> str:
    """条款号归一：'第十一条第三款' → '11-3'；'第3条' → '3'。"""
    a = (article or "").strip()
    if not a:
        return ""
    m = re.match(r"^第([零〇一二三四五六七八九十百千\d]+)条(?:第([零〇一二三四五六七八九十百千\d]+)款)?", a)
    if not m:
        digits = re.findall(r"\d+", a)
        return digits[0] if digits else a
    num = cn2int(m.group(1))
    if num is None:
        return a
    if m.group(2):
        sub = cn2int(m.group(2))
        return f"{num}-{sub}" if sub is not None else str(num)
    return str(num)


class LocalCorpusRetriever(Retriever):
    name = "local-corpus"

    def __init__(self, corpus_dir: str | Path):
        self.dir = Path(corpus_dir)
        #: {归一法名: {归一条款: 原文}}
        self.articles: Dict[str, Dict[str, str]] = {}
        #: 原始法名（保留书名号），用于回显
        self.law_display: Dict[str, str] = {}
        #: [(路径, 全文)]
        self.documents: List[Tuple[str, str]] = []
        self.load()
        self.available = bool(self.articles or self.documents)

    # ------------------------------------------------------------------
    def load(self) -> None:
        if not self.dir.is_dir():
            logger.info("语料目录不存在，检索层为空实现：%s", self.dir)
            return

        for path in sorted(self.dir.rglob("*")):
            if not path.is_file():
                continue
            # README 之类是说明文件，不是语料；否则它的示例引用会被当成"命中"
            stem = path.name.lower()
            if stem.startswith("readme") or path.name.startswith("_"):
                continue
            suffix = path.suffix.lower()
            try:
                if suffix == ".json":
                    self._load_json(path)
                elif suffix in (".md", ".txt"):
                    self.documents.append(
                        (str(path), path.read_text(encoding="utf-8", errors="ignore"))
                    )
            except Exception:  # noqa: BLE001
                logger.warning("语料文件解析失败，已跳过：%s", path, exc_info=True)

        logger.info(
            "语料加载完成：%d 部法律 / %d 份文本（目录 %s）",
            len(self.articles), len(self.documents), self.dir,
        )

    def _load_json(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for law, articles in data.items():
                if not isinstance(articles, dict):
                    continue
                key = norm_law(law)
                self.law_display.setdefault(key, law if law.startswith("《") else f"《{law}》")
                bucket = self.articles.setdefault(key, {})
                for art, text in articles.items():
                    bucket[norm_article(art)] = str(text)
        elif isinstance(data, list):
            for item in data:
                if not isinstance(item, dict) or not item.get("law"):
                    continue
                law = str(item["law"])
                key = norm_law(law)
                self.law_display.setdefault(key, law if law.startswith("《") else f"《{law}》")
                self.articles.setdefault(key, {})[norm_article(str(item.get("article", "")))] = str(
                    item.get("text", "")
                )
        else:
            logger.warning("不认识的 laws JSON 结构：%s", path)

    # ------------------------------------------------------------------
    def lookup(self, law: str, article: str = "") -> Optional[LegalSource]:
        """精确查条款。只有结构化语料能给出确定答案。"""
        key = norm_law(law)
        if key not in self.articles:
            return None
        display = self.law_display.get(key, f"《{key}》")
        if not article:
            # 只给了法律名：返回该部法律的首条作为存在性证据
            first = next(iter(self.articles[key].items()), None)
            if not first:
                return None
            return LegalSource(
                source_type="法律", law=display, article="",
                text=first[1], origin=str(self.dir),
            )
        art_key = norm_article(article)
        text = self.articles[key].get(art_key)
        if text is None:
            return None
        return LegalSource(
            source_type="法律", law=display,
            article=f"第{art_key}条" if "-" not in art_key else f"第{art_key.replace('-', '条第')}款",
            text=text, origin=str(self.dir),
        )

    def law_exists(self, law: str) -> bool:
        return norm_law(law) in self.articles

    # ------------------------------------------------------------------
    def search(self, query: str, k: int = 5) -> List[LegalSource]:
        """极简检索：结构化条款按子串计分，自由文本按 2-gram 重叠计分。

        够用即可——真正接上检索 API 后，这一层会被替换掉。
        """
        q = (query or "").strip()
        if not q:
            return []
        grams = {q[i:i + 2] for i in range(max(len(q) - 1, 1))}
        scored: List[Tuple[float, LegalSource]] = []

        for key, arts in self.articles.items():
            display = self.law_display.get(key, f"《{key}》")
            for art, text in arts.items():
                hay = f"{display}第{art}条{text}"
                score = sum(1 for g in grams if g in hay)
                if score:
                    scored.append((
                        score,
                        LegalSource(source_type="法律", law=display,
                                    article=f"第{art}条", text=text, origin=str(self.dir)),
                    ))

        for origin, text in self.documents:
            score = sum(text.count(g) for g in grams if g in text)
            if score:
                positioned = self._best_window(text, grams)
                scored.append((
                    score * 0.5,  # 自由文本权重低：它无法保证条款对应关系
                    LegalSource(source_type="判例/学说", law="", article="",
                                text=positioned, origin=origin),
                ))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:k]]

    @staticmethod
    def _best_window(text: str, grams: set, width: int = 200) -> str:
        for g in grams:
            idx = text.find(g)
            if idx >= 0:
                start = max(0, idx - width // 2)
                return text[start:start + width].replace("\n", " ").strip()
        return text[:width].replace("\n", " ").strip()

    # ------------------------------------------------------------------
    def stats(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "corpus_dir": str(self.dir),
            "laws": len(self.articles),
            "articles": sum(len(v) for v in self.articles.values()),
            "documents": len(self.documents),
        }
