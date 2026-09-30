"""API 层端到端测试。

用 FastAPI TestClient 打真实路由，数据库指向临时文件（见 conftest.py）。

**全部不调用任何 LLM**：被测的都是本地端点
（会话 / 台账 / 检索 / 引用核验 / 导出 / 指标），
唯一涉及模型的一致性检测只测"没有台账时直接返回空"这条零调用路径。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TESTDATA

SAMPLE_OPPONENT = "著作权法只保护自然人的智力成果，AI 不是人，所以 AI 生成内容不应享有著作权。"


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def session_id(client) -> str:
    resp = client.post("/api/session", json={
        "topic": "AI 生成内容是否应享有著作权",
        "our_side": "控方（主张应享有）",
    })
    assert resp.status_code == 200
    return resp.json()["session"]["id"]


@pytest.fixture(scope="module")
def corpus_ready(client):
    """写入一份临时语料并热加载（用编造的假法名，不写真实法条）。"""
    corpus = TESTDATA / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "laws.json").write_text(
        json.dumps({"《测试法》": {"第三条": "本法所称之成果，指具有独创性者。"}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    client.get("/api/retrieval?reload=true")
    yield


# --------------------------------------------------------------------------
# 健康检查
# --------------------------------------------------------------------------
def test_health_lists_advisors(client):
    data = client.get("/api/health").json()
    assert data["ok"] is True
    names = [a["name"] for a in data["advisors"]]
    assert names == ["rebutter", "questioner", "auditor", "strategist", "risk"]
    assert "budget_s" in data
    # 前端靠这几个字段渲染参谋列，不再自己抄一份名册
    assert data["brand"]
    assert all({"label", "kind", "domain"} <= set(a) for a in data["advisors"])
    kinds = {a["name"]: a["kind"] for a in data["advisors"]}
    assert kinds["rebutter"] == "rebuttal"
    # strategist 是唯一带场景归属的一路（法学专用），如实标出来
    domains = {a["name"]: a["domain"] for a in data["advisors"]}
    assert domains["strategist"] == "法学"
    assert domains["rebutter"] == ""


def test_topics_endpoint_is_reachable_without_corpus(client):
    """辩题库接口不依赖语料也不依赖模型，应当永远可用（哪怕库是空的）。"""
    data = client.get("/api/topics").json()
    assert isinstance(data["topics"], list)
    assert data["count"] == len(data["topics"])


def test_openapi_surface_has_no_llm_probe(client):
    """确保没有留下会误触模型调用的调试端点。"""
    paths = client.get("/openapi.json").json()["paths"]
    for p in paths:
        assert "debug" not in p and "echo" not in p


# --------------------------------------------------------------------------
# 会话与台账
# --------------------------------------------------------------------------
def test_session_roundtrip(client, session_id):
    data = client.get(f"/api/session/{session_id}").json()
    assert data["session"]["id"] == session_id
    assert data["cards"] == []


def test_unknown_session_returns_error(client):
    assert "error" in client.get("/api/session/deadbeef0000").json()


def test_card_lifecycle(client, session_id):
    created = client.post(f"/api/session/{session_id}/cards", json={
        "claim": "著作权法保护的是智力成果的表达",
        "major_premise": "《测试法》第三条",
        "source": "test",
    }).json()
    card_id = created["card"]["id"]
    assert len(created["cards"]) == 1

    patched = client.patch(f"/api/cards/{card_id}", json={"status": "weakened"}).json()
    assert patched["ok"] is True

    cards = client.get(f"/api/session/{session_id}").json()["cards"]
    assert cards[0]["status"] == "weakened"

    assert client.delete(f"/api/cards/{card_id}").json()["ok"] is True
    assert client.get(f"/api/session/{session_id}").json()["cards"] == []


def test_card_invalid_status_is_rejected(client, session_id):
    created = client.post(f"/api/session/{session_id}/cards", json={"claim": "X"}).json()
    card_id = created["card"]["id"]
    resp = client.patch(f"/api/cards/{card_id}", json={"status": "瞎写"}).json()
    assert "error" in resp
    client.delete(f"/api/cards/{card_id}")


def test_consistency_without_cards_costs_nothing(client, session_id):
    """没有台账时一致性检测直接返回空——这条路径不调用模型。"""
    resp = client.post(f"/api/session/{session_id}/check-consistency",
                       json={"claims": ["任意主张"]}).json()
    assert resp["conflicts"] == []


# --------------------------------------------------------------------------
# 检索与引用核验
# --------------------------------------------------------------------------
def test_retrieval_status(client, corpus_ready):
    data = client.get("/api/retrieval").json()
    assert data["available"] is True
    assert data["laws"] == 1 and data["articles"] == 1


def test_verify_citations_three_states(client, corpus_ready, session_id):
    resp = client.post(f"/api/session/{session_id}/verify-citations", json={
        "texts": [
            "依《测试法》第三条。",
            "依《测试法》第九十九条。",
            "依《不存在法》第一条。",
        ]
    }).json()
    assert resp["total"] == 3
    statuses = sorted(i["status"] for i in resp["items"])
    assert statuses == ["dubious", "unverified", "verified"]
    verified = next(i for i in resp["items"] if i["status"] == "verified")
    assert "独创性" in verified["evidence"]


def test_verify_citations_on_empty_session_texts(client, corpus_ready, session_id):
    """该会话没有参谋产出时应返回 0 条，而不是报错。"""
    resp = client.post(f"/api/session/{session_id}/verify-citations", json={
        "texts": ["没有引用的普通句子。"]
    }).json()
    assert resp["total"] == 0


# --------------------------------------------------------------------------
# 指标
# --------------------------------------------------------------------------
def test_metrics_shape(client):
    data = client.get("/api/metrics").json()
    assert "budget_s" in data
    assert isinstance(data["advisors"], dict)


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------
def test_export_markdown_headers(client, session_id):
    resp = client.get(f"/api/session/{session_id}/export.md")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "text/markdown" in resp.headers["content-type"]
    assert "# 辩论参谋复盘" in resp.text


def test_export_docx_is_valid_ooxml(client, session_id):
    resp = client.get(f"/api/session/{session_id}/export.docx")
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"          # OOXML 就是 zip
    assert "wordprocessingml" in resp.headers["content-type"]


def test_export_html_is_print_ready(client, session_id):
    resp = client.get(f"/api/session/{session_id}/export.html")
    assert resp.status_code == 200
    assert "window.print()" in resp.text
    assert "@media print" in resp.text


def test_export_unknown_session(client):
    assert client.get("/api/session/deadbeef0000/export.html").status_code == 404
