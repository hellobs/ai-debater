"""通用参考知识库（无结构 .txt/.md）：上传 → 切块 → 检索 → 注入参谋上下文。

为什么需要它：语料库（data/corpus）是**法条专用**——要求"第X条"行首结构，
这对引用核验是对的；但**通用辩题**没有这种结构。本模块接受任何 .txt/.md
素材（案例摘要、学说笔记、赛题资料），切块后建 char-bigram TF-IDF 索引，
检索 top 块注入参谋上下文的【参考知识】段——让"通用辩手平台"的通用性
有真实的知识面支撑，而不是只靠模型内置知识。

设计取向（借鉴 gemma4-learning-agent 的教训并修正）：
- **证据可追溯**：检索结果带 source / chunk_id / score，注入上下文时保留来源，
  与"引用核验"的求真取向一致；
- **纯 Python、零新依赖**：TF-IDF + 余弦自己写（语料规模是个位数文件，
  scikit-learn 是杀鸡用牛刀）；
- **索引每次构建、不持久化**：文件数少，重建毫秒级——换来了"上传即生效、
  无索引损坏问题"（对方项目用 joblib 持久化反而引入了损坏/版本不匹配的坑）；
- **失败要出声**：解析/编码失败记日志，不做 except: pass。

文件**不入仓**（data/knowledge/ 已 gitignore），与 corpus / ledger 同一约定。
"""
from __future__ import annotations

import logging
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("knowledge")

#: 允许上传的扩展名（与界面的"素材"定位一致：纯文本类）
ALLOWED_EXTS = (".txt", ".md")
#: 单文件大小上限（字节）。素材是辅助上下文，超大文件应先人工裁剪。
MAX_FILE_BYTES = 2 * 1024 * 1024
#: 切块参数：与 gemma4 案例同量级（500 窗 / 90 重叠），但按**段落优先**切
CHUNK_CHARS = 500
OVERLAP_CHARS = 90
#: 注入上下文的块数与最低相关度（低于它的块宁可不注入——噪声比空白更有害）
TOP_K = 3
MIN_SCORE = 0.05

_WS = re.compile(r"[ \t\xa0]+")
_BAD = ("\ufeff", "\u200b", "\u200e", "\u200f")


def _normalize(text: str) -> str:
    for ch in _BAD:
        text = text.replace(ch, "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _WS.sub(" ", text)


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """段落优先的切块：先按空行分段，段内超长再按句号/问号/分号滑窗。

    纯长度滑窗会把概念切在半截（对方的教训之一）；段落/句子边界优先，
    实在超长的"瀑布段"才用带重叠的定长窗兜底。
    """
    text = _normalize(text).strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[str] = []
    for para in paras:
        if len(para) <= size:
            units.append(para)
            continue
        # 段落超长：按句末标点切成句子，再聚合到不超过 size 的窗
        sentences = [s.strip() for s in re.split(r"(?<=[。！？；!?;])", para) if s.strip()]
        cur = ""
        for s in sentences:
            if not cur:
                cur = s
            elif len(cur) + len(s) + 1 <= size:
                cur += " " + s
            else:
                units.append(cur)
                cur = s
        if cur:
            units.append(cur)
    # 相邻短块合并 + 超长块滑窗兜底
    chunks: list[str] = []
    buf = ""
    for u in units:
        if len(buf) + len(u) + 1 <= size:
            buf = f"{buf} {u}".strip()
            continue
        if buf:
            chunks.append(buf)
        if len(u) <= size:
            buf = u
        else:
            step = max(1, size - overlap)
            for i in range(0, len(u), step):
                piece = u[i:i + size]
                if len(piece) >= overlap or i == 0:
                    chunks.append(piece)
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def _bigrams(text: str) -> Counter:
    """char-bigram 计数。中文无需分词，双字粒度对同义改写的容忍度
    远好于整词匹配（对方项目用 word-level TF-IDF 的短板就在这）。"""
    s = re.sub(r"\s+", "", text)
    if len(s) < 2:
        return Counter(s)
    return Counter(s[i:i + 2] for i in range(len(s) - 1))


@dataclass
class KnowledgeChunk:
    source: str
    chunk_id: int
    text: str
    score: float = 0.0

    def to_dict(self) -> dict:
        return {"source": self.source, "chunk_id": self.chunk_id,
                "score": round(self.score, 4), "text": self.text}


class KnowledgeBase:
    """一个目录的知识库。线程安全（重建加锁），索引常驻内存。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._chunks: list[KnowledgeChunk] = []
        self._tf: list[Counter] = []
        self._idf: dict[str, float] = {}

    # ---------------- 索引 ----------------
    def rebuild(self) -> int:
        """重读目录全量重建索引，返回块数。上传/删除后调用——文件数是个位数，
        全量重建毫秒级，换取"上传即生效 + 无持久化损坏"。"""
        with self._lock:
            chunks: list[KnowledgeChunk] = []
            if self.root.is_dir():
                for path in sorted(self.root.iterdir()):
                    if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTS:
                        continue
                    try:
                        text = path.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        logger.warning("知识文件读取失败，已跳过：%s", path.name)
                        continue
                    for i, c in enumerate(chunk_text(text)):
                        chunks.append(KnowledgeChunk(source=path.stem, chunk_id=i, text=c))
            self._chunks = chunks
            self._tf = [_bigrams(c.text) for c in chunks]
            df: Counter = Counter()
            for tf in self._tf:
                df.update(tf.keys())
            n = max(1, len(chunks))
            self._idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
            return len(chunks)

    # ---------------- 检索 ----------------
    def search(self, query: str, top_k: int = TOP_K) -> list[KnowledgeChunk]:
        """char-bigram TF-IDF 余弦检索。空库/空查询返回空。"""
        with self._lock:
            if not self._chunks:
                return []
            q = _bigrams(query)
            if not q:
                return []
            scored: list[KnowledgeChunk] = []
            for chunk, tf in zip(self._chunks, self._tf):
                dot = sum(w * self._idf.get(t, 0.0) * q.get(t, 0.0) * self._idf.get(t, 0.0)
                          for t, w in tf.items() if t in q)
                # 余弦分母：两向量各自的 sqrt(Σ (tf*idf)^2)
                na = math.sqrt(sum((w * self._idf.get(t, 0.0)) ** 2 for t, w in tf.items()))
                nb = math.sqrt(sum((q[t] * self._idf.get(t, 0.0)) ** 2 for t in q))
                score = dot / (na * nb) if na and nb else 0.0
                scored.append(KnowledgeChunk(chunk.source, chunk.chunk_id, chunk.text, score))
            scored.sort(key=lambda c: c.score, reverse=True)
            return [c for c in scored[:top_k] if c.score >= MIN_SCORE]

    # ---------------- 管理 ----------------
    def save(self, name: str, text: str) -> dict:
        """保存一份素材（同名覆盖）。名字清洗成安全文件名。"""
        safe = re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip()).strip("._ ") or "untitled"
        if not safe.lower().endswith(ALLOWED_EXTS):
            safe += ".md"
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / safe
        if target.resolve().parent != self.root.resolve():
            raise ValueError("非法的文件名")
        text = (text or "").strip()
        if not text:
            raise ValueError("内容为空")
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"内容超过 {MAX_FILE_BYTES // 1024 // 1024}MB 上限")
        target.write_text(text + "\n", encoding="utf-8")
        count = self.rebuild()
        return {"name": target.stem, "chunks": count}

    def delete(self, name: str) -> bool:
        """按 stem 删除。save 会自动补扩展名，这里对称尝试（原样/.md/.txt）。"""
        safe = re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip())
        if not safe:
            return False
        target = self.root / safe
        if target.resolve().parent != self.root.resolve():
            return False
        for candidate in (target, target.with_suffix(".md"), target.with_suffix(".txt")):
            if candidate.is_file():
                candidate.unlink()
                self.rebuild()
                return True
        return False

    def status(self) -> dict:
        with self._lock:
            files = {c.source for c in self._chunks}
            return {"files": len(files), "chunks": len(self._chunks),
                    "dir": str(self.root)}


_kb: Optional[KnowledgeBase] = None


def get_kb(root=None) -> KnowledgeBase:
    """进程级单例。测试用 reset() 换目录。"""
    global _kb
    if _kb is None:
        from . import config

        _kb = KnowledgeBase(root or Path(config.KNOWLEDGE_DIR))
        _kb.rebuild()
    return _kb


def reset() -> None:
    global _kb
    _kb = None
