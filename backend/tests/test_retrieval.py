"""检索层与引用核验的单元测试。

全部是**本地纯计算**，不调用任何 LLM。

注意：测试语料用的是**编造的假法名**（《测试法》《样例条例》），
这是刻意的——避免把可能有误的真实法条文本写进仓库，误人。
真实语料由使用者放进 `data/corpus/`。
"""
from __future__ import annotations

import json

import pytest

from app.retrieval import LocalCorpusRetriever, extract, verify_text
from app.retrieval.local_corpus import cn2int, norm_article, norm_law


# --------------------------------------------------------------------------
# 规范化
# --------------------------------------------------------------------------
@pytest.mark.parametrize("src,expected", [
    ("十一", 11), ("二十三", 23), ("一百零一", 101), ("3", 3), ("十", 10),
    ("三十", 30), ("二百", 200),
])
def test_cn2int(src, expected):
    assert cn2int(src) == expected


@pytest.mark.parametrize("src,expected", [
    ("第十一条", "11"),
    ("第11条", "11"),
    ("第十一条第三款", "11-3"),
    ("第三条", "3"),
    ("", ""),
])
def test_norm_article(src, expected):
    assert norm_article(src) == expected


def test_norm_law_strips_book_marks_and_country():
    assert norm_law("《中华人民共和国著作权法》") == "著作权法"
    assert norm_law("《著作权法》") == "著作权法"
    assert norm_law(" 中华人民共和国民法典 ") == "民法典"


# --------------------------------------------------------------------------
# 引用抽取
# --------------------------------------------------------------------------
def test_extract_dedupes_and_splits_fields():
    text = (
        "依《中华人民共和国著作权法》第十一条第三款，以及《著作权法》第十一条第三款，"
        "再辅以《民法典》第五百零九条与《著作权法》。"
    )
    got = extract(text)
    keys = [(law, art) for _, law, art in got]
    assert ("中华人民共和国著作权法", "第十一条第三款") in keys
    assert ("民法典", "第五百零九条") in keys
    assert ("著作权法", "") in keys
    # 同一个 (法名, 条款) 只出现一次
    assert len(keys) == len(set(keys))


# --------------------------------------------------------------------------
# 核验：三级状态
# --------------------------------------------------------------------------
FAKE_LAWS = {
    "《测试法》": {
        "第三条": "本法所称之成果，指具有独创性并能以一定形式表现者。",
        "第十一条": "成果之权利归属于创作者；如无相反证明，署名者为创作者。",
    }
}


@pytest.fixture()
def retriever(tmp_path):
    (tmp_path / "laws.json").write_text(
        json.dumps(FAKE_LAWS, ensure_ascii=False), encoding="utf-8"
    )
    # README 必须被跳过，否则它的示例引用会被当成命中
    (tmp_path / "README.md").write_text(
        "示例：《测试法》第九十九条之规定如下。", encoding="utf-8"
    )
    return LocalCorpusRetriever(tmp_path)


def test_readme_is_not_loaded(retriever):
    assert set(retriever.articles) == {"测试法"}


def test_verified_when_article_exists(retriever):
    rep = verify_text("依《测试法》第三条，该成果具有独创性。", retriever)
    assert rep.total == 1
    assert rep.items[0].status == "verified"
    assert "独创性" in rep.items[0].evidence


def test_dubious_when_law_exists_but_article_missing(retriever):
    rep = verify_text("依《测试法》第九十九条，应当如此。", retriever)
    assert rep.items[0].status == "dubious"
    assert rep.items[0].note


def test_dubious_when_no_article_given(retriever):
    rep = verify_text("依《测试法》之规定，应当如此。", retriever)
    assert rep.items[0].status == "dubious"


def test_unverified_when_law_absent(retriever):
    rep = verify_text("依《根本不存在的法》第一条，应当如此。", retriever)
    assert rep.items[0].status == "unverified"


def test_citation_without_any_corpus_is_unverified():
    from app.retrieval import NullRetriever

    rep = verify_text("依《测试法》第三条，应当如此。", NullRetriever())
    assert rep.total == 1
    assert rep.items[0].status == "unverified"


def test_arabic_and_chinese_article_numbers_are_equivalent(retriever):
    a = verify_text("依《测试法》第3条。", retriever)
    b = verify_text("依《测试法》第三条。", retriever)
    assert a.items[0].status == b.items[0].status == "verified"


def test_mixed_report_counts(retriever):
    text = (
        "依《测试法》第三条；又依《测试法》第九十九条；"
        "再依《不存在法》第一条。"
    )
    rep = verify_text(text, retriever)
    assert rep.total == 3
    assert (rep.verified, rep.dubious, rep.unverified) == (1, 1, 1)


def test_search_returns_sources(retriever):
    hits = retriever.search("独创性", k=3)
    assert hits
    assert hits[0].law == "《测试法》"
    assert hits[0].rank <= 1          # 法律位阶应排在最前
