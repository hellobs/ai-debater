"""项目配置读取层：只从环境变量取，绝不落盘凭据。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# mavis 侧（喂给框架的配置）
MAVIS_CONFIG_PATH = os.environ.get(
    "MAVIS_CONFIG_PATH", str(ROOT / "configs" / "mavis" / "config.json")
)
MAVIS_ASSETS_ROOT = os.environ.get(
    "MAVIS_ASSETS_ROOT", str(ROOT / "configs" / "mavis" / "assets")
)
MAVIS_PROMPT_DIR = os.environ.get(
    "MAVIS_PROMPT_DIR", str(ROOT / "configs" / "mavis" / "prompts")
)
MAVIS_CHECKPOINTS_ROOT = os.environ.get(
    "MAVIS_CHECKPOINTS_ROOT", str(ROOT / "data" / "checkpoints")
)

# 我方桥（mavis 指向它）
LLM_BRIDGE_HOST = os.environ.get("LLM_BRIDGE_HOST", "127.0.0.1")
LLM_BRIDGE_PORT = int(os.environ.get("LLM_BRIDGE_PORT", "8011"))
LLM_BRIDGE_URL = os.environ.get(
    "LLM_BRIDGE_URL", f"http://{LLM_BRIDGE_HOST}:{LLM_BRIDGE_PORT}/v1"
)

# 模型（非敏感）
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

# 数据
DATA_DIR = ROOT / "data"
LEDGER_DB = os.environ.get("LEDGER_DB", str(DATA_DIR / "ledger.db"))


def upstream_configured() -> bool:
    """上游凭据是否就位（只报布尔，不泄露值）。"""
    return bool(os.environ.get("ANTHROPIC_BASE_URL")) and bool(
        os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
