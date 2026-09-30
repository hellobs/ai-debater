"""upstream 读空白 token 时应当被识别为「未配置」。

背景：`backend/app/upstream.py` 之前在多处用裸 `os.environ.get("ANTHROPIC_*", "")`。
后果：OS-level `export ANTHROPIC_AUTH_TOKEN=""` 或 `_load_dotenv` 之后
在 OS-level 留了空串的边角场景下，`upstream._initial()` 拿到的 `api_key` 仍是空串，
但 `bool("")` 是 False ⇒ `key_set` 应为 False。改用 `config._env` 之后这条不变，但
锁死「未来不要退回 `os.environ.get`」这条约定。
"""
from __future__ import annotations

import pytest

from app import config, upstream


@pytest.fixture(autouse=True)
def _isolate_upstream_env(monkeypatch):
    """本组测试在干净 env 下跑，避免污染进程级单例与其他用例。"""
    # .env 加载已经把 ANTHROPIC_AUTH_TOKEN 注进 os.environ；
    # 这里把它清掉再跑，等同"OS-level 空白 + .env 空白"的真实边角场景
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_VERSION", raising=False)
    monkeypatch.delenv("UPSTREAM_KIND", raising=False)
    # 把可能的 LLM_BRIDGE_URL 也设到空（_initial 用 :11434 推断 ollama）
    monkeypatch.setenv("LLM_BRIDGE_URL", "http://127.0.0.1:9/v1")
    yield


def test_blank_token_is_reported_as_not_set():
    """修复后：_initial() 拿空白 token 时 key_set 仍为 False。"""
    s = upstream._initial()
    assert s.api_key == ""
    assert bool(s.api_key) is False
    assert s.public()["key_set"] is False


def test_blank_base_url_is_treated_as_empty_not_default():
    """修复后：_initial() 在 BASE_URL 留空时拿到的也是空串，
    不会回落到某个隐式默认值（这会让人误以为配好了）。"""
    s = upstream._initial()
    assert s.base_url == ""


def test_empty_token_does_not_come_from_os_environ_get(monkeypatch):
    """这条断言锁死修复意图：
    `_initial()` 不能从 `os.environ.get` 路径读 token，否则 OS-level 空白
    会被当真实值（即便 `bool` 仍是 False，也失去 `config._env` 的统一防线）。
    """
    import app.upstream as u
    src = open(u.__file__, encoding="utf-8").read()
    assert "os.environ.get(\"ANTHROPIC_AUTH_TOKEN\"" not in src, (
        "upstream.py 又退回裸 os.environ.get("
        "ANTHROPIC_AUTH_TOKEN ...) —— 这会绕过 config._env 的空白防线。"
    )
    assert "config._env(\"ANTHROPIC_AUTH_TOKEN\"" in src, (
        "upstream.py 应通过 config._env 读 ANTHROPIC_AUTH_TOKEN。"
    )