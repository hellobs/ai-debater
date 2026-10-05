"""协议桥的第二道门：「现在到底该不该服务」（**0 真实消耗**：上游是测试内起的本地 mock）。

这道门补的是第一道门的残余面
---------------------------
`test_bridge_origin.py` 那组证明：跨站请求被 403 挡下。但来源校验**刻意**放行
"不带来源"的调用（mavis 用 httpx 调桥本就没有 Origin），于是本机的 `curl`、
脚本、随手一个 Python 文件仍然能打 `/v1/chat/completions` —— 而只要上游形态是
anthropic，桥手里就握着一把能烧额度的云端 key。

体检给出的可选加固就是本文件：**上游不是 anthropic 时，桥拒不服务**。
那时 mavis 走的是直连（`upstream.Settings.mavis_base_url` 只有 anthropic 才指本桥），
桥本来就毫无用处，让它闭嘴不影响任何正常流程。

三条断言都要有：
- 状态码 503（不是 403：这不是来源问题，是"这条路径现在没人走"）；
- **上游命中数为 0**（钱这一层才是重点）；
- 切回 anthropic 立刻恢复 200 —— 防止"修复过头"把唯一的调用方也断了。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import llm_bridge, upstream

PAYLOAD = {"model": "probe", "messages": [{"role": "user", "content": "hi"}]}


class _Mock(BaseHTTPRequestHandler):
    """只记账的假上游。`status` 可改，用来演非 200 的失败分支。"""

    hits: list[dict] = []
    status = 200

    def do_POST(self):
        # 同 test_bridge_origin._Mock：不读完请求体就响应会在客户端侧炸 ReadError
        # （间歇性 502，与用例顺序相关）。
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        _Mock.hits.append({"path": self.path, "api_key": self.headers.get("x-api-key")})
        out = json.dumps({
            "id": "t", "type": "message", "role": "assistant", "model": "t",
            "content": [{"type": "text", "text": '{"res":{}}'}],
        }).encode()
        self.send_response(_Mock.status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture()
def client():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old = (llm_bridge.CFG.base, llm_bridge.CFG.token, upstream.current().kind)
    llm_bridge.CFG.base = f"http://127.0.0.1:{srv.server_address[1]}"
    llm_bridge.CFG.token = "sk-test-fake"
    _Mock.hits.clear()
    yield TestClient(llm_bridge.app)
    upstream.update(kind=old[2])
    llm_bridge.CFG.base, llm_bridge.CFG.token = old[0], old[1]
    srv.shutdown()
    srv.server_close()


def test_ollama_upstream_bridge_refuses(client):
    """本机 Ollama 形态：mavis 直连，桥不受理。"""
    upstream.update(kind="ollama")
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert resp.status_code == 503
    assert "桥未启用" in resp.text
    assert _Mock.hits == []  # 关键：没有上游调用，一次额度都没花


def test_openai_upstream_bridge_refuses(client):
    """OpenAI 兼容端点同理（mavis 也直连）。"""
    upstream.update(kind="openai")
    assert client.post("/v1/chat/completions", json=PAYLOAD).status_code == 503
    assert _Mock.hits == []


def test_refusal_precedes_origin_check(client):
    """不在路径上时，先拒路径，不再问来源 —— 跨站打过来也一样 503。"""
    upstream.update(kind="ollama")
    resp = client.post("/v1/chat/completions", json=PAYLOAD,
                       headers={"Origin": "https://evil.example"})
    assert resp.status_code == 503
    assert _Mock.hits == []


def test_serving_again_when_anthropic(client):
    """切回 anthropic 立刻恢复服务 —— 防止"修复过头"把唯一调用方也断了。"""
    upstream.update(kind="ollama")
    assert client.post("/v1/chat/completions", json=PAYLOAD).status_code == 503
    upstream.update(kind="anthropic")
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert resp.status_code == 200
    assert len(_Mock.hits) == 1
    assert _Mock.hits[0]["api_key"] == "sk-test-fake"


def test_healthz_reports_serving_flag(client):
    """healthz 必须说清"为什么不响应"，否则排查只能靠猜。"""
    upstream.update(kind="ollama")
    off = client.get("/healthz").json()
    assert off["serving"] is False
    # 凭据还配着（没动它）—— 这正是这道门存在的理由：那把 key 明明还在，却打不出去
    assert off["upstream_configured"] is True
    upstream.update(kind="anthropic")
    assert client.get("/healthz").json()["serving"] is True


# --------------------------------------------------------------------------
# 上游失败：不能只回一个空 content
# --------------------------------------------------------------------------
def test_upstream_error_carries_marker_and_real_status(client):
    """上游非 200 时，桥必须让**调用方**能分辨出这是失败。

    此前三条失败分支都 `return _openai_body("", model)` —— HTTP 200 + 空 content。
    mavis 不读状态码、只读 content，于是把"上游挂了"记成 `status="empty"`，
    界面显示「未返回内容。」，与"模型真没话说"一模一样，真因只在后端日志里。
    """
    _Mock.status = 500
    try:
        resp = client.post("/v1/chat/completions", json=PAYLOAD)
    finally:
        _Mock.status = 200

    assert resp.status_code == 502, "状态码要如实反映失败（此前一律 200）"
    body = resp.json()
    # 关键：body 仍是**合法的 OpenAI 响应体** —— mavis 对非 JSON 响应会走
    # 10 次重试 × sleep(5)，把失败拖成 50 秒静默。这条不能破。
    content = body["choices"][0]["message"]["content"]
    assert content.startswith(llm_bridge.BRIDGE_ERROR_PREFIX)
    assert "500" in content


def test_success_body_has_no_marker(client):
    """反向断言：成功路径不能被哨兵污染 —— 否则正常产出会被误判成失败。"""
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert resp.status_code == 200
    assert not resp.json()["choices"][0]["message"]["content"].startswith(
        llm_bridge.BRIDGE_ERROR_PREFIX
    )


def test_mavis_bridge_turns_marker_into_error(monkeypatch):
    """`mavis_bridge.complete()` 要把哨兵翻成异常 → `Advisor.run` 报 `status="error"`。"""
    from app import mavis_bridge

    class _Provider:
        def completion(self, *a, **kw):
            return f"{llm_bridge.BRIDGE_ERROR_PREFIX} 上游 HTTP 401"

    monkeypatch.setattr(mavis_bridge, "get_provider", lambda: _Provider())
    with pytest.raises(RuntimeError, match="401"):
        mavis_bridge.complete("prompt")


def test_mavis_bridge_passes_normal_text_through(monkeypatch):
    """正常文本必须原样返回 —— 这道识别不能误伤生产路径。"""
    from app import mavis_bridge

    class _Provider:
        def completion(self, *a, **kw):
            return '{"res": "正常产出"}'

    monkeypatch.setattr(mavis_bridge, "get_provider", lambda: _Provider())
    assert mavis_bridge.complete("prompt") == '{"res": "正常产出"}'
