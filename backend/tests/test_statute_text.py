"""法律全文 → 结构化条款的解析测试。

全部是**本地纯文本处理**，不调用任何 LLM。为了跑通：

- 测试文本是**编造的假法条**（《测试法》《样例条例》），条文内容是占位句子。
  这是刻意的——避免把可能有误的真实法条文本写进仓库误人（与 test_retrieval.py 同一约定）。
"""
from __future__ import annotations

import pytest

from app.retrieval.statute_text import (
    StatuteParseError,
    article_no,
    guess_law_name,
    int2cn,
    parse_statute_text,
)


# --------------------------------------------------------------------------
# 中文数字
# --------------------------------------------------------------------------
@pytest.mark.parametrize("n,expected", [
    (1, "一"), (9, "九"), (10, "十"), (11, "十一"), (20, "二十"), (30, "三十"),
    (99, "九十九"), (100, "一百"), (101, "一百零一"), (105, "一百零五"),
    (110, "一百一十"), (200, "二百"), (260, "二百六十"), (999, "九百九十九"),
    (1000, "一千"), (1260, "一千二百六十"), (12345, "12345"),
])
def test_int2cn(n, expected):
    assert int2cn(n) == expected


@pytest.mark.parametrize("key,expected", [
    ("第一条", 1), ("第十一条", 11), ("第一百零一条", 101), ("第11条", 11),
])
def test_article_no(key, expected):
    assert article_no(key) == expected


# --------------------------------------------------------------------------
# 法名识别
# --------------------------------------------------------------------------
def test_guess_law_name_from_first_line():
    assert guess_law_name(["测试法", "", "第一章 总则"]) == "测试法"


def test_guess_law_name_skips_long_lines():
    """发布信息那种长行不该被当法名。"""
    lines = ["（1990年1月1日某次会议通过，自公布之日起施行）", "样例条例"]
    assert guess_law_name(lines) == "样例条例"


# --------------------------------------------------------------------------
# 基本切分
# --------------------------------------------------------------------------
BASIC = """\
测试法

第一章 总则

第一条 这是第一条的占位正文，用于验证切分。
第二行属于同一条，应当被并入上一条。

第二条 这是第二条的占位正文。

第二章 分则

第三条 这是第三条的占位正文。

- 3 -
"""


def test_basic_split():
    res = parse_statute_text(BASIC)
    assert res.law == "测试法"
    assert list(res.articles) == ["第一条", "第二条", "第三条"]
    assert res.count == 3
    assert res.missing == []


def test_wrapped_lines_merged():
    """同一条内的多行要被拼成一段。"""
    res = parse_statute_text(BASIC)
    assert "这是第一条的占位正文" in res.articles["第一条"]
    assert "第二行属于同一条" in res.articles["第一条"]


def test_chapter_heading_not_leaked_into_body():
    """章标题夹在两条之间，不能混进上一条的正文。"""
    res = parse_statute_text(BASIC)
    assert "第二章" not in res.articles["第二条"]
    assert "分则" not in res.articles["第二条"]


def test_page_number_line_dropped():
    res = parse_statute_text(BASIC)
    assert "- 3 -" not in res.articles["第三条"]


# --------------------------------------------------------------------------
# 最关键的一条：交叉引用不能被当成条款起始
# --------------------------------------------------------------------------
CROSSREF = """\
样例条例

第一条 依照本条例第五条的规定处理，具体见第五条第二款。

第二条 前条所称情形，适用本条例第九条。

第三条 本条为最后一条。
"""


def test_cross_reference_does_not_split():
    """正文里的「第X条」若在行中间，不得被当作条款起始。"""
    res = parse_statute_text(CROSSREF)
    assert list(res.articles) == ["第一条", "第二条", "第三条"]
    assert "依照本条例第五条的规定处理" in res.articles["第一条"]
    assert "适用本条例第九条" in res.articles["第二条"]


# --------------------------------------------------------------------------
# 编号与容错
# --------------------------------------------------------------------------
def test_arabic_numeral_normalized_to_chinese():
    text = "测试法\n第一条 甲。\n第2条 乙。\n第3条 丙。\n"
    res = parse_statute_text(text)
    assert list(res.articles) == ["第一条", "第二条", "第三条"]


def test_missing_article_numbers_reported():
    text = "测试法\n第一条 甲。\n第二条 乙。\n第五条 戊。\n"
    res = parse_statute_text(text)
    assert res.missing == [3, 4]
    assert "缺号" in res.summary()


def test_warns_when_first_article_absent():
    """只导入某一编时，前面的条号也应如实列为缺失（语料不完整的信号）。"""
    text = "测试法\n第三条 甲。\n第四条 乙。\n第五条 丙。\n"
    res = parse_statute_text(text)
    assert any("缺少第一条" in w for w in res.warnings)
    assert res.missing == [1, 2]


def test_shorter_than_threshold_raises():
    """条款太少说明多半不是法律全文（比如被硬换行成整段）。"""
    with pytest.raises(StatuteParseError) as e:
        parse_statute_text("测试法\n第一条 只有一条。\n")
    assert "行首锚定" in str(e.value)


def test_blank_article_skipped_with_warning():
    text = "测试法\n第一条 甲。\n第二条 　\n第三条 丙。\n"
    res = parse_statute_text(text)
    assert "第二条" not in res.articles
    assert any("正文为空" in w for w in res.warnings)


def test_explicit_law_name_overrides_guess():
    res = parse_statute_text(BASIC, law="《样例条例》")
    assert res.law == "《样例条例》"


def test_missing_law_name_warns():
    res = parse_statute_text("第一条 甲。\n第二条 乙。\n第三条 丙。\n")
    assert res.law == ""
    assert any("未能从正文猜出法名" in w for w in res.warnings)


# --------------------------------------------------------------------------
# 与检索层对接：解析结果要能直接喂进 LocalCorpusRetriever
# --------------------------------------------------------------------------
def test_parsed_output_feeds_retriever(tmp_path):
    """导入产出的结构，必须能被检索层读成「已核验」。"""
    import json

    from app.retrieval import LocalCorpusRetriever, verify_text

    res = parse_statute_text(BASIC)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "laws.json").write_text(
        json.dumps({res.law: res.articles}, ensure_ascii=False), encoding="utf-8"
    )

    retriever = LocalCorpusRetriever(corpus)
    assert retriever.available

    report = verify_text("依《测试法》第三条的规定，应当如此。", retriever)
    assert report.total == 1
    assert report.items[0].status == "verified"
    assert report.items[0].evidence                      # 附了原文为证

    # 该法存在但没有这一条 → 存疑（不是"已核验"）
    gap = verify_text("依《测试法》第九条第九款的规定，应当如此。", retriever)
    assert gap.items[0].status == "dubious"
