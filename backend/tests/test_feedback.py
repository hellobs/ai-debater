"""反馈闭环测试：/api/feedback 端点 + 持久化核验报告 + 导出（双门槛/偏好对）。

全部 0 API 消耗。数据库与语料目录由 conftest 指向 .testdata。
"""
from __future__ import annotations

import json

import pytest

from app import asr as _asr  # noqa: F401  — 确保 asr 包初始化顺序与生产一致
from app import config
from app.feedback import build_pairs, build_samples
from app.ledger import store
from tests.conftest import TESTDATA


@pytest.fixture()
def session_with_suggestions(client):
    """建会话 + 直插两路产出（模拟一轮分析完成）。"""
    sid = client.post("/api/session", json={"topic": "反馈闭环测试", "our_side": "正方"}).json()["session"]["id"]
    store.save_suggestion(sid, type("R", (), {
        "advisor": "rebutter", "status": "ok", "latency_s": 1.0,
        "payload": [{"claim": "权利可归使用者，无需赋予 AI 主体资格",
                     "major_premise": "权利主体与保护对象可以分离",
                     "minor_premise": "对方把主体资格当成了讨论前提",
                     "conclusion": "应先讨论保护再讨论归属"}],
    })())
    store.save_suggestion(sid, type("R", (), {
        "advisor": "risk", "status": "ok", "latency_s": 1.0,
        "payload": [{"risk": "对方可能追问独创性标准", "kind": "对方陷阱",
                     "suggestion": "提前准备两级标准"}],
    })())
    client.post(f"/api/session/{sid}/turns-check", json={}) if False else None
    return sid


# --------------------------------------------------------------------------
# /api/feedback
# --------------------------------------------------------------------------
def test_feedback_upsert_by_session_and_advisor(client, session_with_suggestions):
    sid = session_with_suggestions
    assert client.post(f"/api/feedback?session_id={sid}",
                       json={"advisor": "rebutter", "rating": 5, "selected": True}).json()["ok"]
    # 同 (session, advisor) 再评一次 → upsert 而非堆行
    client.post(f"/api/feedback?session_id={sid}",
                json={"advisor": "rebutter", "rating": 4, "selected": True})
    rows = client.get(f"/api/feedback?session_id={sid}").json()["feedback"]
    assert len(rows) == 1 and rows[0]["rating"] == 4 and rows[0]["selected"] == 1


def test_feedback_rejects_bad_rating(client, session_with_suggestions):
    sid = session_with_suggestions
    resp = client.post(f"/api/feedback?session_id={sid}",
                       json={"advisor": "rebutter", "rating": 9})
    assert resp.status_code == 400


def test_feedback_unknown_session(client):
    resp = client.post("/api/feedback?session_id=nope",
                       json={"advisor": "rebutter", "rating": 5})
    assert resp.json().get("error") == "session not found"


def test_feedback_requires_csrf_header():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as bare:   # 不带防护头 → 403
        resp = bare.post("/api/feedback?session_id=x", json={"advisor": "a"})
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# 证据落库：verify → 持久化 → GET latest 回读
# --------------------------------------------------------------------------
def test_citation_report_persisted_and_restored(client, session_with_suggestions):
    sid = session_with_suggestions
    corpus = TESTDATA / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "laws.json").write_text(json.dumps(
        {"《测试法》": {"第一条": "测试条文内容。"}}, ensure_ascii=False), encoding="utf-8")
    client.get("/api/retrieval?reload=true")

    client.post(f"/api/session/{sid}/verify-citations", json={
        "texts": ["依据《测试法》第一条，测试条文内容。"]})
    got = client.get(f"/api/session/{sid}/citations/latest").json()
    assert got["report"] is not None and got["report"]["total"] == 1
    # 刷新场景：不重算也能取回**同一份**报告（status 由语料测试专管，
    # 这里只守"持久化 → 读回一致"，不耦合语料状态）
    again = client.get(f"/api/session/{sid}/citations/latest").json()
    assert again["report"] == got["report"]


def test_citations_latest_empty_is_null(client):
    sid = client.post("/api/session", json={"topic": "无报告会话", "our_side": "正"}).json()["session"]["id"]
    assert client.get(f"/api/session/{sid}/citations/latest").json()["report"] is None


# --------------------------------------------------------------------------
# 导出：双门槛样本 + 偏好对
# --------------------------------------------------------------------------
def test_samples_gate_selected_and_rating(client, session_with_suggestions):
    sid = session_with_suggestions
    # 只有 rebutter 达标（勾选 + 评分 5）；risk 未勾选；score=2 分不够线
    client.post(f"/api/feedback?session_id={sid}", json={"advisor": "rebutter", "rating": 5, "selected": True})
    client.post(f"/api/feedback?session_id={sid}", json={"advisor": "risk", "rating": 5, "selected": False})
    client.post(f"/api/feedback?session_id={sid}", json={"advisor": "questioner", "rating": 2, "selected": True})
    store.save_suggestion(sid, type("R", (), {
        "advisor": "questioner", "status": "ok", "latency_s": 1.0,
        "payload": ["问题一？", "问题二？"]})())

    samples, counts = build_samples(min_rating=4)
    # 库里累积着此前各轮的反馈行：按本会话过滤后断言，不写死全库总数
    mine = [f for f in store.list_feedback(sid)]
    assert len(mine) == 3 and counts["feedback_rows"] >= 3
    mine_samples = [s for s in samples if s["meta"]["session_id"] == sid]
    assert len(mine_samples) == 1 and mine_samples[0]["meta"]["advisor"] == "rebutter"
    assert "对方发言" in mine_samples[0]["messages"][0]["content"]


def test_pairs_from_adopted_edited_card(client, session_with_suggestions):
    """采纳时改了笔 → (rejected=原文, chosen=采纳版) 偏好对；原样采纳不成对。"""
    sid = session_with_suggestions
    client.post(f"/api/session/{sid}/cards", json={
        "claim": "权利应配置给使用者而非 AI 本体，这才是制度的落脚点",   # 改过笔
        "major_premise": "权利主体与保护对象可以分离",
        "source": "rebutter",
    })
    pairs, counts = build_pairs()
    assert counts["cards"] >= 1
    # 库里会累积此前各轮的合法偏好对：按本次会话断言，不写死总数
    mine = [p for p in pairs if p["meta"]["session_id"] == sid]
    assert len(mine) == 1
    assert "使用者" in mine[0]["chosen"]["claim"]
    assert mine[0]["rejected"]["claim"].startswith("权利可归使用者")
