"""CSRF 防护测试（main.py csrf_guard + asr_stream 的 Origin 校验）。

威胁模型（第三轮体检 P2）：恶意网页借**用户浏览器**向本机后端发跨站"简单请求"
（GET / text/plain POST，不触发 CORS 预检），触发 5 次真实计费、或向语料库写入
编造内容。防线：计费/写盘端点强制自定义头 `X-Debater-UI: 1` —— 浏览器无法在
跨站简单请求里携带自定义头（会触发预检被拦），故带头 ≈ 来自本界面。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def bare_client():
    """**不带**防护头的客户端——模拟恶意网页发起的跨站简单请求。"""
    with TestClient(app) as c:
        yield c


def test_billing_endpoint_rejected_without_guard_header(bare_client):
    # /api/analyze 会真实调用模型计费：无头必须 403，且错误消息说人话
    resp = bare_client.post("/api/analyze", json={
        "topic": "t", "opponent_text": "o",
    })
    assert resp.status_code == 403
    assert "X-Debater-UI" in resp.json()["detail"]


def test_legacy_stream_get_rejected_without_guard_header(bare_client):
    # 保留给脚本的 GET SSE 同样计费 → 同规则
    resp = bare_client.get("/api/analyze/stream", params={
        "topic": "t", "opponent_text": "o",
    })
    assert resp.status_code == 403


def test_corpus_import_rejected_without_guard_header(bare_client):
    # 语料库写入（把编造内容固化成"已核验"的通道）
    resp = bare_client.post("/api/corpus/import", json={"text": "《X》\n第一条 甲。"})
    assert resp.status_code == 403


def test_reads_stay_open_without_guard_header(bare_client):
    # GET 读接口不涉钱不落盘：放行（恶意网页也读不到跨源响应）
    assert bare_client.get("/api/health").status_code == 200
    assert bare_client.get("/api/topics").status_code == 200


def test_bridge_exempt_from_guard_header(bare_client):
    """协议桥的调用方是 mavis 进程（服务端），绝不能要求浏览器头 —— 这是本条的重点。

    顺带把上游先摘掉再打：这条测的是**守卫豁免**，不测上游。此前不摘，于是
    「测试环境配没配上游」会改变走哪条分支（未配置 → 503 / 上游非 200 → 502），
    断言只能写成 `== 503`，一旦本机带着 `ANTHROPIC_AUTH_TOKEN` 就会踩到 502；
    更糟的是它**会真的往上游发请求**（测试纪律：0 真实 API 调用）。
    这里显式走"未配置"分支，两条都消掉。
    """
    from app import llm_bridge

    old = (llm_bridge.CFG.base, llm_bridge.CFG.token)
    llm_bridge.CFG.base, llm_bridge.CFG.token = "", ""
    try:
        resp = bare_client.post("/bridge/v1/chat/completions", json={
            "model": "m", "messages": [{"role": "user", "content": "hi"}],
        })
    finally:
        llm_bridge.CFG.base, llm_bridge.CFG.token = old[0], old[1]

    assert resp.status_code != 403, "桥不能被 CSRF 守卫拦住"
    assert resp.status_code == 503, "未配置上游时桥要如实回 503（见 llm_bridge._bridge_failure）"
    # body 仍必须是可被 mavis 解析的合法 OpenAI 体 —— mavis 不读状态码，
    # 只认 content，且对非 JSON 响应会走 10 次重试 × sleep(5)。
    body = resp.json()
    assert body["choices"][0]["message"]["content"].startswith("__BRIDGE_ERROR__")


def test_guard_header_accepted(client):
    # conftest 的 client 默认带头（模拟真实 UI）→ 计费端点正常受理
    # （用 stream 端点 + mock 探针路径，不真跑模型——run_advisors 已在
    #   test_stream_budget.py 里被替换的技巧这里不重复，直接看受理状态码即可）
    resp = client.post("/api/analyze", json={
        "topic": "guard", "opponent_text": "o", "budget_s": 0,
    })
    assert resp.status_code == 200


def test_websocket_cross_site_origin_rejected():
    # 浏览器 WS 必带 Origin；跨站时 Origin host ≠ Host → 拒绝（1008）
    with pytest.raises(Exception):
        with TestClient(app).websocket_connect(
            "/api/asr/stream",
            headers={"Origin": "https://evil.example"},
        ) as ws:
            ws.receive_json()


def test_websocket_same_origin_allowed():
    # 同源（Origin host == Host）→ 正常进入端点（模型未下载 → error 帧而非拒绝）
    with TestClient(app) as c:
        c.headers["Origin"] = str(c.base_url)  # 同源：Origin == Host
        with c.websocket_connect("/api/asr/stream") as ws:
            msg = ws.receive_json()
            assert msg["type"] in ("ready", "error")
