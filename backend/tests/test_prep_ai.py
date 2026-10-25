"""备赛 AI（/api/prep/ai）测试。

零上游消耗：用 monkeypatch 把 mavis_bridge.complete 换成记录器——
测的是任务校验、提示词组装（反幻觉纪律折叠在头部）与失败语义，
不测模型本身。
"""
from __future__ import annotations

import pytest

from app import prep as prep_mod
from app.prep import PrepAIRequest, run_prep_ai


@pytest.fixture()
def captured(monkeypatch):
    calls: dict = {}

    def fake_complete(prompt, retry=2, caller="prep", **kwargs):
        calls["prompt"] = prompt
        calls["caller"] = caller
        return "【AI 产出】这是一段备赛材料。"

    monkeypatch.setattr(prep_mod, "complete", fake_complete)
    return calls


def test_split_task_folds_antihallucination_into_prompt(captured):
    r = run_prep_ai(PrepAIRequest(task="split", topic="AI 生成内容应不应该强制标注", side="正方"))
    assert r["ok"] is True
    assert captured["caller"] == "prep_split"
    # 反幻觉纪律必须折叠在提示词头部（mavis 无独立 system 位）
    assert "严禁编造案例" in captured["prompt"]
    assert "辩题：AI 生成内容应不应该强制标注" in captured["prompt"]
    # 拆题任务要求输出 JSON 字段
    assert "clashes" in captured["prompt"]


def test_supply_and_draft_tasks(captured):
    r = run_prep_ai(PrepAIRequest(task="supply", topic="T", materials={"def": "已有定义"}))
    assert r["ok"] is True and "已有材料" in captured["prompt"]
    r = run_prep_ai(PrepAIRequest(task="draft", topic="T", materials={"a1": "论点一"}))
    assert r["ok"] is True and "稿件材料" in captured["prompt"]


def test_unknown_task_and_empty_topic_rejected(captured):
    assert run_prep_ai(PrepAIRequest(task="bad", topic="T"))["ok"] is False
    assert run_prep_ai(PrepAIRequest(task="split", topic="  "))["ok"] is False


def test_failsafe_and_bridge_error_surface_as_error(monkeypatch):
    from app.mavis_bridge import FAILED

    monkeypatch.setattr(prep_mod, "complete", lambda *a, **k: FAILED)
    r = run_prep_ai(PrepAIRequest(task="draft", topic="T"))
    assert r["ok"] is False and "重试耗尽" in r["error"]

    monkeypatch.setattr(
        prep_mod, "complete",
        lambda *a, **k: "__BRIDGE_ERROR__ 上游 500",
    )
    from app.llm_bridge import BRIDGE_ERROR_PREFIX
    monkeypatch.setattr(prep_mod, "bridge_error", lambda out: out.replace(BRIDGE_ERROR_PREFIX, "").strip())
    r = run_prep_ai(PrepAIRequest(task="draft", topic="T"))
    assert r["ok"] is False and "上游 500" in r["error"]


def test_endpoint_requires_csrf_and_wires_through(client, monkeypatch):
    # 无头 403（CSRF 防线覆盖新端点）
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as bare:
        assert bare.post("/api/prep/ai", json={"task": "split", "topic": "T"}).status_code == 403
    # 带头 + mock complete → 透传
    monkeypatch.setattr(
        "app.main.prep_mod.complete",
        lambda *a, **k: "【AI 产出】ok",
    )
    resp = client.post("/api/prep/ai", json={"task": "split", "topic": "T"})
    assert resp.status_code == 200 and resp.json()["ok"] is True
