"""真实导入语料的离线集成测试（0 调用、纯本地）。

`test_retrieval.py` 用的是凭空编的《测试法》，只验证**核验逻辑**本身；
本文件验证的是 **「加入真语料」这件事真的落地了**：

1. 导入管线（`import_corpus.py` + `parse_statute_text`）把官方来源的全文
   切成正确的条款数（著作权法 67 条 / 个人信息保护法 74 条 / 民法典 1260 条 / 刑法 451 条 等）；
2. 真实 `data/corpus/laws.json` 能被 `LocalCorpusRetriever` / `get_retriever`
   加载，且 `available=True`、含 8 部法律 / 2366 条；
3. 已知真实条文（著作权法第24条合理使用、PIPL第13条处理合法性基础、
   PIPL第24条算法价格歧视、专利法第22条三性、刑法第232条故意杀人、
   民法典第1019条肖像权、反不正当竞争法第7条商业贿赂、行政许可法第8条信赖保护、
   刑事诉讼法第55条证明标准）核验为 verified 且证据命中原文；
4. 编造的条款号（著作权法第99条）→ dubious；语料里没有的法（南极条约）→ unverified；
5. 真实条款号 + 编造内容（著作权法第11条）→ 存在性 verified，但内容对不上
   （content_ok=False），这正是本项目要防的"幻觉引用"那一种。

语料来自官方政府网站镜像（国家法律法规数据库同源），来源写在
`data/corpus/sources/*.txt` 头部。若 `data/corpus/laws.json` 不在仓库里，
本文件整体跳过（不影响一次干净 clone 上的其余测试）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]          # ai-debater/
sys.path.insert(0, str(ROOT / "backend"))

from app.retrieval import (  # noqa: E402
    MATCH_LOW,
    LocalCorpusRetriever,
    get_retriever,
    verify_text,
)
from app.retrieval.statute_text import parse_statute_text  # noqa: E402

REAL_CORPUS = ROOT / "data" / "corpus"
LAWS_JSON = REAL_CORPUS / "laws.json"

pytestmark = pytest.mark.skipif(
    not LAWS_JSON.exists(),
    reason="data/corpus/laws.json 未导入，跳过真实语料集成测试",
)


# --------------------------------------------------------------------------
# 导入管线：源文件 → 结构化条款数
# --------------------------------------------------------------------------
def _find_source(name: str) -> Path:
    """源文件名可能带 `_source_` 之类的前缀（原始来源标记），按关键字匹配。"""
    src = REAL_CORPUS / "sources"
    assert src.is_dir(), f"语料源目录缺失：{src}"
    hit = next(
        (p for p in src.glob("*.txt") if name in p.name and not p.name.lower().startswith("readme")),
        None,
    )
    assert hit is not None, f"找不到 {name} 的源文件（已检查 {src}）"
    return hit


#: 每部已导入源文件的预期条款数（与 data/corpus/laws.json 的键计数一致）。
_SOURCE_ARTICLE_COUNTS = [
    ("著作权法", 67),
    ("个人信息保护法", 74),
    ("专利法", 82),
    ("刑法", 451),
    ("刑事诉讼法", 308),
    ("反不正当竞争法", 41),
    ("民法典", 1260),
    ("行政许可法", 83),
]


@pytest.mark.parametrize("name,expected", _SOURCE_ARTICLE_COUNTS)
def test_source_files_parse_to_expected_article_counts(name, expected):
    r = parse_statute_text(
        _find_source(name).read_text(encoding="utf-8"),
        law=f"中华人民共和国{name}",
    )
    assert r.count == expected, r.summary()


# --------------------------------------------------------------------------
# 真实 laws.json 被检索层加载
# --------------------------------------------------------------------------
def test_real_corpus_loads_via_local_retriever():
    r = LocalCorpusRetriever(REAL_CORPUS)
    assert r.available
    stats = r.stats()
    assert stats["laws"] == 8
    assert stats["articles"] == 2366


def test_real_corpus_loads_via_get_retriever_default_path():
    # 默认路径就是 data/corpus，正是运行中的后端在用的那条
    os.environ.pop("CORPUS_DIR", None)
    r = get_retriever(force_reload=True)
    assert r.available
    assert r.stats()["laws"] == 8
    assert r.stats()["articles"] == 2366


@pytest.fixture()
def retriever():
    os.environ["CORPUS_DIR"] = str(REAL_CORPUS)
    return get_retriever(force_reload=True)


# --------------------------------------------------------------------------
# 已知真实条文 → verified，且证据命中原文
# --------------------------------------------------------------------------
def test_known_copyright_article_verified(retriever):
    rep = verify_text(
        "依《中华人民共和国著作权法》第二十四条，合理使用可不经许可、不付报酬。",
        retriever,
    )
    it = rep.items[0]
    assert it.status == "verified"
    assert "第二十四条" in it.article
    assert "不经" in it.evidence and "著作权人许可" in it.evidence


def test_known_pipl_consent_article_verified(retriever):
    rep = verify_text(
        "《中华人民共和国个人信息保护法》第十三条明确了处理个人信息的合法性基础。",
        retriever,
    )
    it = rep.items[0]
    assert it.status == "verified"
    assert "第十三条" in it.article
    assert "取得个人的同意" in it.evidence


def test_known_pipl_price_discrimination_article_verified(retriever):
    # 第24条正是"大数据杀熟/算法价格歧视"的规制依据
    rep = verify_text(
        "《中华人民共和国个人信息保护法》第二十四条禁止基于自动化决策实行不合理的差别待遇。",
        retriever,
    )
    it = rep.items[0]
    assert it.status == "verified"
    assert "第二十四条" in it.article
    assert "自动化决策" in it.evidence and "差别待遇" in it.evidence


# --------------------------------------------------------------------------
# 新导入部门法的代表性真实条文 → verified（覆盖全部 8 部法律）
# --------------------------------------------------------------------------
@pytest.mark.parametrize("text,article", [
    ("《中华人民共和国专利法》第二十二条定义了发明的新颖性、创造性和实用性。", "第二十二条"),
    ("《中华人民共和国民法典》第一千零一十九条规定了肖像权保护。", "第一千零一十九条"),
    ("《中华人民共和国刑法》第二百三十二条规定了故意杀人罪。", "第二百三十二条"),
    ("《中华人民共和国反不正当竞争法》第七条规制商业贿赂。", "第七条"),
    ("《中华人民共和国行政许可法》第八条规定了信赖保护原则。", "第八条"),
    ("《中华人民共和国刑事诉讼法》第五十五条规定了证据确实充分的证明标准。", "第五十五条"),
])
def test_new_laws_known_articles_verified(retriever, text, article):
    rep = verify_text(text, retriever)
    it = rep.items[0]
    assert it.status == "verified"
    assert article in it.article
    assert it.evidence


# --------------------------------------------------------------------------
# 编造条款号 / 未知法律 → 正确降级
# --------------------------------------------------------------------------
def test_fabricated_article_number_is_dubious(retriever):
    rep = verify_text("《中华人民共和国著作权法》第九十九条规定……", retriever)
    it = rep.items[0]
    assert it.status == "dubious"
    assert "没有这一条" in (it.note or "")


def test_unknown_law_is_unverified(retriever):
    # 南极条约不在语料库里（8 部均为国内部门法），应判 unverified
    rep = verify_text("《南极条约》第三条规定……", retriever)
    it = rep.items[0]
    assert it.status == "unverified"


def test_law_name_only_without_article_is_dubious(retriever):
    rep = verify_text("依据《中华人民共和国个人信息保护法》的相关规定……", retriever)
    it = rep.items[0]
    assert it.status == "dubious"


# --------------------------------------------------------------------------
# 内容一致性：真实条款号 + 编造内容 → 存在性 verified 但 content_ok=False
# --------------------------------------------------------------------------
def test_real_article_with_accurate_claim_is_ok(retriever):
    rep = verify_text(
        "《中华人民共和国著作权法》第十一条规定：著作权属于作者。",
        retriever,
    )
    it = rep.items[0]
    assert it.status == "verified"
    assert it.claimed == "著作权属于作者"
    assert it.content_ok is True


def test_real_article_with_fabricated_claim_flagged(retriever):
    """最要命的幻觉：条款号是真的，内容是编的。对真实语料也必须能抓出来。"""
    rep = verify_text(
        "《中华人民共和国著作权法》第十一条规定：任何人可无限制复制他人作品且无需署名。",
        retriever,
    )
    it = rep.items[0]
    assert it.status == "verified"           # 存在性：第11条确实在语料里
    assert it.content_ok is False             # 一致性：引述内容对不上原文
    assert it.match is not None and it.match < MATCH_LOW
    assert rep.content_suspect == 1
