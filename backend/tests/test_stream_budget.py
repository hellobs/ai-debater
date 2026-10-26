"""时间预算与桥超时的**契约**测试（0 API 消耗）。

背景（体检 2026-09-30）：前端曾把 budget_s=0「省略不发送」，后端遂落到
自己的默认档 —— 界面上「不限」实际是 30s。修复后前端**总是显式发送**预算；
这里的用例锁住后端的接收契约，防止三处口径再次漂移。
"""
from __future__ import annotations

import pytest

from app import config


@pytest.fixture()
def captured_run(monkeypatch):
    """把 stream 端点里真正跑参谋的 run_advisors 换成记录器。

    通过传入的 plugins 管理器补发 run_end，让 SSE 的 done 哨兵正常到达、
    事件流能收尾——否则 event_gen 会永远等下去。
    """
    captured: dict = {}

    def fake_run(ctx, roster, on_result=None, retry=2, budget_s=None, plugins=None):
        captured["budget_s"] = budget_s
        captured["roster_names"] = [a.name for a in roster]
        if plugins is not None:
            plugins.emit({"type": "run_end", "total_latency_s": 0.0})
        return [], 0.0

    monkeypatch.setattr("app.main.run_advisors", fake_run)
    return captured


def _consume_until_done(client, params: dict) -> None:
    with client.stream("GET", "/api/analyze/stream", params=params) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("event: done"):
                return
    raise AssertionError("SSE 流在 done 事件前结束")


def test_stream_budget_zero_reaches_orchestrator(client, captured_run):
    """「不限」= 0 必须原样到达编排器（编排器据此关闭到点交付）。"""
    _consume_until_done(
        client,
        {"topic": "预算契约测试", "opponent_text": "对方的发言", "budget_s": "0"},
    )
    assert captured_run["budget_s"] == 0


def test_stream_budget_absent_falls_back_to_server_default(client, captured_run):
    """省略参数 = 用服务端默认档（第三方直调 API 的既有语义，保持不变）。"""
    _consume_until_done(
        client, {"topic": "预算契约测试", "opponent_text": "对方的发言"}
    )
    assert captured_run["budget_s"] == config.ADVISOR_BUDGET_S


def test_stream_post_form_also_passes_budget_through(client, captured_run):
    """P2-1 之后前端在用 POST 形态：预算契约在 POST 下同样成立。"""
    with client.stream(
        "POST",
        "/api/analyze/stream",
        json={"topic": "预算契约测试", "opponent_text": "对方的发言", "budget_s": 0},
    ) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("event: done"):
                break
    assert captured_run["budget_s"] == 0


def test_stream_advisors_filter_reaches_orchestrator(client, captured_run):
    """快反模式：advisors=['rebutter','risk'] → 编排器只收到这两路（过滤在端点层）。"""
    _consume_until_done(
        client,
        {"topic": "快反", "opponent_text": "对方的短句", "budget_s": "8",
         "advisors": ["rebutter", "risk"]},
    )
    assert captured_run["roster_names"] == ["rebutter", "risk"]


def test_analyze_advisors_empty_runs_zero(client, captured_run):
    """显式空列表 = 跑零路（与名册全停用同语义，不静默改回）。

    空数组在 GET query 里无法表达（httpx 省略空参数）——走 POST body 验证。"""
    resp = client.post("/api/analyze", json={
        "topic": "快反", "opponent_text": "对方的短句", "budget_s": 0, "advisors": [],
    })
    assert resp.status_code == 200
    assert captured_run["roster_names"] == []


def test_bridge_timeout_is_never_tighter_than_llm_timeout():
    """桥先超时 → 返回空体 → mavis 重试烧钱。这条不变式已由代码取 max 保证。"""
    from app import llm_bridge

    assert llm_bridge.TIMEOUT >= config.LLM_TIMEOUT_S
