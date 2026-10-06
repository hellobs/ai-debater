"""上游可运行时配置 / 模型探测。

这一组守的是三件事，每件都对应一个真实的翻车方式：

1. **凭据不对外** —— 有了配置界面之后，密钥第一次有可能被"返回给前端"。
   对外只能有 `key_set: bool`。
2. **切换真的生效** —— mavis 的 provider 在构造时就把地址定死了，忘了重建
   provider 的表现是"界面显示已切换、实际还在打旧地址"，而且**照旧计费**。
3. **"不动" ≠ "清空"** —— 界面上只换模型时不提交密钥字段，若把缺失当清空，
   用户换一次模型就得重填一次密钥。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import upstream
from app.main import app

client = TestClient(app)
# 模拟真实 UI：计费/写盘端点要求 CSRF 防护头（main.py csrf_guard）
client.headers["X-Debater-UI"] = "1"


@pytest.fixture
def restore_upstream():
    """测试改的是进程级单例，用完必须还原 —— 否则会污染后面的用例。"""
    before = upstream.current()
    saved = (before.kind, before.base_url, before.model, before.api_key)
    yield
    upstream.update(kind=saved[0], base_url=saved[1], model=saved[2], api_key=saved[3])


def test_public_snapshot_never_leaks_the_key(restore_upstream):
    upstream.update(kind="openai", base_url="https://example.invalid/v1",
                    model="m", api_key="sk-secret-value")
    body = client.get("/api/upstream").json()["upstream"]
    assert body["key_set"] is True
    # 序列化后的整个报文里都不该出现明文
    assert "sk-secret-value" not in str(body)


def test_switching_kind_changes_where_mavis_points(restore_upstream):
    upstream.update(kind="ollama", base_url="http://127.0.0.1:11434/v1", model="qwen3:8b")
    assert client.get("/api/health").json()["upstream"]["mavis_base_url"] == \
        "http://127.0.0.1:11434/v1"

    upstream.update(kind="anthropic", base_url="https://gw.invalid", model="deepseek-chat")
    health = client.get("/api/health").json()
    # anthropic 形态下 mavis 打的是内嵌桥，不是用户填的那个网关地址
    assert health["upstream"]["mavis_base_url"].endswith("/bridge/v1")
    assert health["upstream"]["base_url"] == "https://gw.invalid"
    assert health["model"] == "deepseek-chat"


def test_switching_upstream_rebuilds_the_provider(restore_upstream):
    """不重建 provider 的话，界面显示切了、实际还在打旧地址。"""
    from app import mavis_bridge

    mavis_bridge.get_provider()                       # 先建一个
    before = mavis_bridge.get_provider()
    upstream.update(kind="ollama", base_url="http://127.0.0.1:11434/v1", model="x")
    client.post("/api/upstream", json={"kind": "ollama",
                                       "base_url": "http://127.0.0.1:11434/v1",
                                       "model": "x"})
    assert mavis_bridge.get_provider() is not before


def test_unknown_kind_is_rejected(restore_upstream):
    resp = client.post("/api/upstream", json={"kind": "gemini"})
    assert resp.status_code == 400
    # 被拒之后不该留下半改状态
    assert upstream.current().kind != "gemini"


def test_omitted_key_keeps_the_old_one(restore_upstream):
    upstream.update(kind="openai", base_url="https://example.invalid/v1",
                    model="a", api_key="sk-keep")
    client.post("/api/upstream", json={"model": "b"})   # 只换模型
    assert upstream.current().api_key == "sk-keep"
    assert upstream.current().model == "b"

    client.post("/api/upstream", json={"api_key": ""})  # 明确清空
    assert upstream.current().api_key == ""


def test_probe_failure_is_reported_not_raised(restore_upstream):
    """探测不到就如实报错 —— 不拿写死的清单冒充"可用模型"。"""
    models, err, probed = upstream.probe_models(kind="ollama", base_url="http://127.0.0.1:9/v1")
    assert models == []
    assert err                      # 有话可说，不是吞掉异常
    assert probed["base_url"] == "http://127.0.0.1:9/v1"

    resp = client.get("/api/models", params={"kind": "ollama",
                                             "base_url": "http://127.0.0.1:9/v1"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert resp.json()["models"] == []


def test_anthropic_host_shows_the_gateway_not_the_bridge(restore_upstream):
    """切到云端之后，「上游 · 主机」必须还是那个网关。

    实测踩点（2026-10-06）：anthropic 形态下 host() 取的是内嵌桥的地址，于是
    切到 api.deepseek.com 之后界面仍显示「上游 Anthropic · 127.0.0.1:8010」——
    看不出钱花在哪儿。桥的地址在 health 里另有「接入地址」一行，这里不必重复。
    """
    upstream.update(kind="anthropic", base_url="https://api.deepseek.com/anthropic",
                    model="deepseek-flash")
    host = upstream.current().public()["host"]
    assert host == "api.deepseek.com"


def test_anthropic_model_list_falls_back_to_another_path(monkeypatch):
    """清单挂在别的路径上不算"不支持" —— 404 之后退一步再试。

    实测 DeepSeek（2026-10-06）：`/anthropic/v1/models` 是 404，而 `/models` 给
    得出清单，消息端点 `/anthropic/v1` 却照常收 anthropic 头。只认一个路径的话，
    界面上「刷新模型列表」必然报 404，用户会以为配置填错了。
    """
    calls = []

    def fake_get_json(url, headers=None):
        calls.append(url)
        if url.endswith("/anthropic/v1/models"):
            return None, "HTTP 404"
        return {"data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]}, ""

    monkeypatch.setattr(upstream, "_get_json", fake_get_json)
    models, err = upstream._anthropic_models("https://api.deepseek.com/anthropic", "k")
    assert err == ""
    assert models == ["deepseek-flash", "deepseek-v4-pro"]
    assert calls == ["https://api.deepseek.com/anthropic/v1/models",
                     "https://api.deepseek.com/models"]


def test_anthropic_model_list_still_reports_real_unsupported(monkeypatch):
    """回退不能把真不支持也吞掉 —— 两次都拿不到清单时，必须如实报错给界面。"""
    monkeypatch.setattr(upstream, "_get_json",
                        lambda url, headers=None: (None, "HTTP 404"))
    models, err = upstream._anthropic_models("https://gw.invalid/anthropic", "k")
    assert models == []
    assert "HTTP 404" in err
    assert "gw.invalid" in err


def test_probe_result_says_which_config_it_belongs_to(restore_upstream):
    """清单必须连着"从哪份配置探来的"一起给。

    否则界面会出现最误导人的状态：改了形态/地址还没重探，屏幕上却摆着
    上一个端点的模型名 —— 照着点就填了一个这个端点根本没有的模型。
    """
    upstream.update(kind="openai", base_url="https://a.invalid/v1", model="m")
    _, _, probed = upstream.probe_models()          # 不带参数 = 当前配置
    assert probed == {"kind": "openai", "base_url": "https://a.invalid/v1"}

    _, _, probed = upstream.probe_models(kind="ollama", base_url="http://127.0.0.1:11434/v1")
    assert probed == {"kind": "ollama", "base_url": "http://127.0.0.1:11434/v1"}
