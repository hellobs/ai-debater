"""协议桥的来源校验回归（**0 真实消耗**：上游是测试内起的本地 mock）。

为什么需要这组测试
------------------
`main.py` 的 csrf_guard 把 `/bridge` 整条豁免（调用方 mavis 是服务端进程，
发不出 `X-Debater-UI` 头）。补上桥自己的来源校验之后，这条豁免才不再等于
"谁都能打"。体检实测（2026-10-04）：跨站 `text/plain` 的 POST —— 浏览器
「简单请求」，不发预检、用不上自定义头 —— 能带着 `x-api-key` 打到上游，
替调用者烧额度。校验必须**发生在碰上游之前**，所以这里既断言状态码，
也断言上游命中数。

最后两条用例是防「修复过头」：mavis 用 httpx 调桥本来就不带 Origin，
误伤了就直接断掉模型调用。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import llm_bridge

PAYLOAD = {"model": "probe", "messages": [{"role": "user", "content": "hi"}]}


class _Mock(BaseHTTPRequestHandler):
    """只记账的假上游。"""

    hits: list[dict] = []

    def do_POST(self):
        _Mock.hits.append({"path": self.path, "api_key": self.headers.get("x-api-key")})
        out = json.dumps({
            "id": "t", "type": "message", "role": "assistant", "model": "t",
            "content": [{"type": "text", "text": '{"res":{}}'}],
        }).encode()
        self.send_response(200)
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
    old = (llm_bridge.CFG.base, llm_bridge.CFG.token)
    llm_bridge.CFG.base = f"http://127.0.0.1:{srv.server_address[1]}"
    llm_bridge.CFG.token = "sk-test-fake"
    _Mock.hits.clear()
    yield TestClient(llm_bridge.app)
    llm_bridge.CFG.base, llm_bridge.CFG.token = old
    srv.shutdown()
    srv.server_close()


def test_cross_site_origin_rejected(client):
    resp = client.post("/v1/chat/completions", json=PAYLOAD,
                       headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert "跨站" in resp.text
    assert _Mock.hits == []  # 关键：一次额度都没花


def test_cross_site_simple_request_rejected(client):
    """浏览器 text/plain POST 不发预检、用不上自定义头 —— 最危险的那条路径。"""
    resp = client.post(
        "/v1/chat/completions",
        content=json.dumps(PAYLOAD),
        headers={"Origin": "https://evil.example", "Content-Type": "text/plain"},
    )
    assert resp.status_code == 403
    assert _Mock.hits == []


def test_cross_site_referer_rejected(client):
    resp = client.post("/v1/chat/completions", json=PAYLOAD,
                       headers={"Referer": "https://evil.example/x"})
    assert resp.status_code == 403
    assert _Mock.hits == []


def test_local_dev_origin_allowed(client):
    resp = client.post("/v1/chat/completions", json=PAYLOAD,
                       headers={"Origin": "http://127.0.0.1:5173"})
    assert resp.status_code == 200
    assert len(_Mock.hits) == 1


def test_loopback_hostname_allowed(client):
    resp = client.post("/v1/chat/completions", json=PAYLOAD,
                       headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert len(_Mock.hits) == 1


def test_no_origin_allowed(client):
    """mavis 用 httpx 调桥的自然形态：没有 Origin，不能被误伤。"""
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert resp.status_code == 200
    assert len(_Mock.hits) == 1
    assert _Mock.hits[0]["api_key"] == "sk-test-fake"  # 凭据照常带上，功能没坏
