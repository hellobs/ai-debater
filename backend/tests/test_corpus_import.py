"""语料导入端点测试。

**全部 0 API 消耗**：导入是纯本地文件操作 + 文本解析（与 CLI
`scripts/import_corpus.py` 共用 `statute_text.parse_statute_text`）。
语料目录被 conftest 指到 `.testdata/corpus`，不碰仓库真实语料。

核验链路（导入 → 检索层热重载 → 引用翻「已核验」）一并覆盖——
导入的价值就在那一环，只测写入等于没测。
"""
from __future__ import annotations

import json

import pytest

from tests.conftest import TESTDATA


@pytest.fixture(autouse=True)
def clean_store():
    """每个用例前清掉语料文件。

    这是被真实咬过的一口：损坏测试写坏的 laws.json 会留在 .testdata 里，
    把下一次运行的全部用例毒成大面积报错——错误隔离必须做到文件级。
    """
    (TESTDATA / "corpus" / "laws.json").unlink(missing_ok=True)
    yield
    (TESTDATA / "corpus" / "laws.json").unlink(missing_ok=True)

#: 假法名 + 三条假条文（编造的，不是真实法条——测试不许固化错误语料）
SAMPLE = """《测试导入法》

第一条 为了测试导入功能，制定本法。
第二条 导入的文本应当被结构化。
第三条 本法自测试日起施行。
"""

REPLACED = """《测试导入法》

第一条 为了测试导入功能，制定本法。
第二条 导入的文本应当被结构化。
第三条 修订后的第三条。
第四条 修订时新增的条款。
"""


def test_import_then_citation_turns_verified(client):
    resp = client.post("/api/corpus/import", json={"text": SAMPLE})
    data = resp.json()
    assert resp.status_code == 200 and data["ok"] is True
    assert data["law"] == "测试导入法"
    assert data["articles"] == 3

    # 端点已热重载检索层（不必再 ?reload=true）
    status = client.get("/api/retrieval").json()
    assert status["available"] is True

    # 引用核验翻「已核验」——这是导入存在的意义
    rep = client.post(
        "/api/session/import-test/verify-citations",
        json={"texts": ["依据《测试导入法》第三条，本法自测试日起施行。"]},
    ).json()
    assert rep["total"] == 1
    assert rep["items"][0]["status"] == "verified"
    assert rep["items"][0]["law"] == "测试导入法"


def test_reimport_same_law_replaces_wholesale(client):
    client.post("/api/corpus/import", json={"text": SAMPLE})
    resp = client.post("/api/corpus/import", json={"text": REPLACED})
    data = resp.json()
    assert data["ok"] is True and data["articles"] == 4
    # 旧版第三条的原文应已被替换（整体替换，不是逐条合并留旧）
    store = json.loads(
        (TESTDATA / "corpus" / "laws.json").read_text(encoding="utf-8")
    )
    assert "修订后的第三条" in store["测试导入法"]["第三条"]
    assert store["测试导入法"]["第一条"] == "为了测试导入功能，制定本法。"


def test_import_empty_text_is_an_error(client):
    data = client.post("/api/corpus/import", json={"text": "   "}).json()
    assert "正文为空" in data["error"]


def test_import_without_law_name_is_an_error(client):
    # 有条款行但认不出法名，也没填 law 参数——法名是核验对齐的键，宁可报错
    data = client.post(
        "/api/corpus/import",
        json={"text": "第一条 甲。\n第二条 乙。\n第三条 丙。"},
    ).json()
    assert data["ok"] is False
    assert "法名" in data["error"]


def test_import_text_without_articles_is_an_error(client):
    # 整段没有行首「第X条」——解析器拒绝猜测，错误要能指到怎么修
    data = client.post(
        "/api/corpus/import",
        json={"text": "《无条款法》这是一整段没有条款行首锚定的文本。"},
    ).json()
    assert data["ok"] is False and "error" in data


def test_corrupt_store_reports_instead_of_wiping(client):
    # 先放一份好语料，再把 laws.json 写坏：导入必须报错，**不能**静默重建
    ok = client.post("/api/corpus/import", json={"text": SAMPLE}).json()
    assert ok["ok"] is True
    path = TESTDATA / "corpus" / "laws.json"
    path.write_text("{这不是JSON", encoding="utf-8")
    data = client.post("/api/corpus/import", json={"text": SAMPLE}).json()
    assert data["ok"] is False and "合法 JSON" in data["error"]
