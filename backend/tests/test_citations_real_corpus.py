"""离线引用核验回归：用真实语料（data/corpus/laws.json）证明核验链路端到端可用。

不调用任何 LLM，0 API 消耗。目的：锁定「法学能力从提示词咒语变成可证伪」这条。
导入真实法条后，引用核验应当能区分四种情况：

1. 真实条款 + 真实内容        → verified 且 content_ok
2. 真实条款 + 编造内容        → verified（存在性成立）但 content_ok=False
3. 真实法律 + 不存在的条款号  → dubious
4. 语料里没有的法律           → unverified

真实语料由 `scripts/import_corpus.py` 从官方发布源生成（见 data/corpus/sources/ 的出处注释）。
若 laws.json 缺失，本测试会直接失败并提示先导入。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.retrieval import LocalCorpusRetriever, verify_text

ROOT = Path(__file__).resolve().parents[2]
REAL_CORPUS = ROOT / "data" / "corpus"


@pytest.fixture(scope="module")
def retriever() -> LocalCorpusRetriever:
    r = LocalCorpusRetriever(REAL_CORPUS)
    assert r.available, "真实语料未加载——请先运行 scripts/import_corpus.py 导入 data/corpus/laws.json"
    return r


def test_real_corpus_loaded(retriever: LocalCorpusRetriever) -> None:
    stats = retriever.stats()
    assert stats["laws"] >= 2, f"语料法律数偏少：{stats['laws']}"
    assert stats["articles"] >= 130, f"语料条款数偏少：{stats['articles']}"


def test_real_article_verified_with_real_content(retriever: LocalCorpusRetriever) -> None:
    # 著作权法第24条 = 合理使用。
    real = retriever.lookup("著作权法", "第24条")
    assert real is not None, "著作权法第24条未在语料中"
    claimed = real.text[:24]  # 模型准确引述了条文开头
    rep = verify_text(f"对方援引《著作权法》第24条：{claimed}", retriever)
    assert rep.total == 1
    item = rep.items[0]
    assert item.status == "verified"
    assert item.content_ok is True, f"真实内容却被判对不上：match={item.match}"


def test_pip_automated_decision_verified(retriever: LocalCorpusRetriever) -> None:
    # 个人信息保护法第24条 = 自动化决策 / 算法价格歧视。
    real = retriever.lookup("个人信息保护法", "第24条")
    assert real is not None, "个人信息保护法第24条未在语料中"
    claimed = real.text[:24]
    rep = verify_text(f"《个人信息保护法》第24条规定：{claimed}", retriever)
    item = rep.items[0]
    assert item.status == "verified"
    assert item.content_ok is True


def test_bogus_article_is_dubious(retriever: LocalCorpusRetriever) -> None:
    # 法在语料里、但条款号不存在 → 存疑（可能是编造，也可能语料不全）
    rep = verify_text("《著作权法》第999条规定……", retriever)
    assert rep.items[0].status == "dubious"


def test_unknown_law_is_unverified(retriever: LocalCorpusRetriever) -> None:
    # 语料里没有这部法律 → 未核验
    rep = verify_text("《外星人权益保护法》第1条规定……", retriever)
    assert rep.items[0].status == "unverified"


def test_real_article_with_fabricated_content_is_suspect(
    retriever: LocalCorpusRetriever,
) -> None:
    # 条款号真实、但引述内容编造 → 存在性仍 verified，内容却对不上（content_suspect）
    text = "《著作权法》第10条明确：任何作品都可以被任意复制，且无需署名。"
    rep = verify_text(text, retriever)
    item = rep.items[0]
    assert item.status == "verified"
    assert item.content_ok is False, "编造内容应当被判对不上"
    assert rep.content_suspect == 1
