"""llm_bridge 的环境变量读取复用 config._env 的回归测试。

关键回归点：此前 llm_bridge 在模块级用
`int(os.environ.get("LLM_BRIDGE_MAX_TOKENS", "2048"))` 这类裸读取，
一旦变量被设为**空串**（照 `.env.example` 填空值很常见），import 期就会
`ValueError: invalid literal for int()` 直接崩，服务起不来。

改为 `config._env`（空白值视为未设置 → 回退默认值）后，空值不再致命。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]          # ai-debater/
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))


def test_blank_numeric_env_does_not_crash_at_import(monkeypatch):
    monkeypatch.setenv("LLM_BRIDGE_MAX_TOKENS", "")
    monkeypatch.setenv("LLM_BRIDGE_TIMEOUT", "")
    import app.llm_bridge as bridge

    # 重新执行模块级常量求值，模拟"带着空值环境变量冷启动"
    importlib.reload(bridge)

    # 空值回退到默认，而非崩溃
    assert bridge.DEFAULT_MAX_TOKENS == 2048
    assert bridge.TIMEOUT == 120.0


def test_numeric_env_override_is_respected(monkeypatch):
    monkeypatch.setenv("LLM_BRIDGE_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_BRIDGE_TIMEOUT", "60")
    import app.llm_bridge as bridge

    importlib.reload(bridge)

    assert bridge.DEFAULT_MAX_TOKENS == 4096
    assert bridge.TIMEOUT == 60.0
