"""检索层与引用核验的单元测试。

全部是**本地纯计算**，不调用任何 LLM。

注意：测试语料用的是**编造的假法名**（《测试法》《样例条例》），
这是刻意的——避免把可能有误的真实法条文本写进仓库，误人。
真实语料由使用者放进 `data/corpus/`。
"""
from __future__ import annotations

import json

import pytest

from app.retrieval import MATCH_LOW, LocalCorpusRetriever, extract, verify_text
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


# --------------------------------------------------------------------------
# 内容一致性：条款存在 ≠ 引述内容是对的
#
# 这是"存在性核验"之外的第二维。旧版只查条款号，于是模型可以写一个**真实存在**
# 的条款号再配一段**编造**的条文内容，系统照样判「已核验」——实测发生过
# （见 docs/local-model-report.md）。
# --------------------------------------------------------------------------
def test_claimed_content_is_extracted_after_colon(retriever):
    rep = verify_text(
        "《测试法》第三条：本法所称之成果，指具有独创性并能以一定形式表现者。", retriever
    )
    it = rep.items[0]
    assert it.status == "verified"
    assert it.claimed.startswith("本法所称之成果")
    assert it.match == 1.0            # 逐字引述，重合度拉满
    assert it.content_ok is True


def test_paraphrase_is_not_treated_as_a_mismatch(retriever):
    """意译概括不该被误判成"引述对不上" —— 低重合是给人的信号，不是自动判决。"""
    rep = verify_text("依《测试法》第三条，该成果具有独创性。", retriever)
    it = rep.items[0]
    assert it.status == "verified"
    assert it.match is not None and it.match >= MATCH_LOW
    assert it.content_ok is True
    assert rep.content_suspect == 0


def test_fabricated_content_on_a_real_article_is_flagged(retriever):
    """最要命的一种幻觉：条款号是真的，内容是编的。"""
    rep = verify_text(
        "《测试法》第十一条规定：AI 生成的内容一律享有著作权，因为 AI 是作者。", retriever
    )
    it = rep.items[0]
    assert it.status == "verified"        # 存在性：这一条确实在语料里
    assert it.content_ok is False         # 一致性：但模型引述的内容对不上
    assert it.match is not None and it.match < MATCH_LOW
    assert it.claimed                  # 把模型原话留着，人才看得见差在哪
    assert rep.content_suspect == 1


def test_no_claimed_content_means_no_content_verdict(retriever):
    """模型只给条款号、没写内容 → 不硬凑一个结论出来。"""
    rep = verify_text("依《测试法》第三条。", retriever)
    it = rep.items[0]
    assert it.status == "verified"
    assert it.claimed == ""
    assert it.match is None and it.content_ok is None
    assert rep.content_suspect == 0


def test_semicolon_right_after_a_citation_is_not_swallowed_as_content(retriever):
    """引用后紧跟分号 → 没内容可比；绝不能把后面那半句抓过来当引述。"""
    rep = verify_text("依《测试法》第三条；又依《测试法》第九十九条。", retriever)
    assert all(i.claimed == "" for i in rep.items)


def test_content_check_never_changes_the_existence_status(retriever):
    """两个维度正交：内容对不上，`status` 依然是 verified。"""
    rep = verify_text(
        "《测试法》第十一条：AI 生成的内容一律享有著作权，因为 AI 是作者。", retriever
    )
    it = rep.items[0]
    assert it.status == "verified"
    assert it.content_ok is False
    assert rep.verified == 1 and rep.dubious == 0 and rep.unverified == 0


def test_too_short_a_claim_is_not_compared(retriever):
    """声称内容太短比不出名堂 —— 宁可不结论，也不给一个噪声值。

    "AI 是作者"去掉标点只剩 4 个字，拿它算重合度只会得到一个随机数。
    """
    rep = verify_text("《测试法》第十一条：AI 是作者。", retriever)
    it = rep.items[0]
    assert it.claimed == ""
    assert it.match is None and it.content_ok is None


def test_report_carries_the_threshold_so_the_ui_does_not_duplicate_it(retriever):
    rep = verify_text("依《测试法》第三条。", retriever)
    assert rep.match_low == MATCH_LOW
    assert rep.to_dict()["match_low"] == MATCH_LOW
