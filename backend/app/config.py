"""项目配置读取层：只从环境变量取，绝不落盘凭据。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 站点品牌名。前端顶栏与 FastAPI title 同源，避免两处各写一遍。
# 平台是**通用辩手参谋台**；「AI + 法学」是它的落地场景之一，不作为品牌。
BRAND_NAME = os.environ.get("BRAND_NAME", "辩手参谋台")

# 注：mavis 的 provider 配置**不在**这里读取。项目只借它的 create_llm_provider()，
# 参数由 backend/app/mavis_bridge.py 直接构造 dict 传入（见该文件）。
# 此前为 mavis 的 Simulator 预留的 MAVIS_CONFIG_PATH / ASSETS_ROOT /
# CHECKPOINTS_ROOT 三个环境变量从未被任何代码读取，已删除。

# 我方桥（mavis 指向它）
LLM_BRIDGE_HOST = os.environ.get("LLM_BRIDGE_HOST", "127.0.0.1")
LLM_BRIDGE_PORT = int(os.environ.get("LLM_BRIDGE_PORT", "8011"))
LLM_BRIDGE_URL = os.environ.get(
    "LLM_BRIDGE_URL", f"http://{LLM_BRIDGE_HOST}:{LLM_BRIDGE_PORT}/v1"
)

# 模型（非敏感）
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

# 模型并发上限（mavis provider 的全局信号量大小）
LLM_CONCURRENCY = os.environ.get("LLM_CONCURRENCY", "4")

# 单次分析的时间预算（秒）。超过预算仍未返回的参谋会被标 timeout 并立刻交付。
# 现场模式建议 12s；备赛/宽松模式可放宽到 30s 甚至 0（=不限）。
ADVISOR_BUDGET_S = float(os.environ.get("ADVISOR_BUDGET_S", "20"))

# 参谋团名册
ADVISORS_YAML = os.environ.get(
    "ADVISORS_YAML", str(ROOT / "configs" / "advisors.yaml")
)

# 提示词模板目录。
# 提示词走 mavis 的模板层（`mavisframework.prompt.Scratch.build_prompt`），
# 所以目录直接复用 mavis 自己认的环境变量名 `MAVIS_PROMPT_DIR`。
# 这里把它读进 config，是为了让"模板从哪来"只有一个来源（下面 assign 给 Scratch）。
#
# 目录结构：顶层 `layout.txt` 是总装骨架；各领域包在 `packs/<包名>/{roles,tasks}/` 下。
# 哪个包上场由辩题的 domain 决定，映射写在下面这份配置里（见 app/prompt_packs.py）。
PROMPT_DIR = Path(
    os.environ.get("MAVIS_PROMPT_DIR", str(ROOT / "prompts"))
)

# 领域提示词包配置：domain → 用哪一套参谋措辞
PROMPT_PACKS_YAML = os.environ.get(
    "PROMPT_PACKS_YAML", str(ROOT / "configs" / "prompt-packs.yaml")
)

# 后端自身
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("API_PORT", "8010"))

# 数据
DATA_DIR = ROOT / "data"
LEDGER_DB = os.environ.get("LEDGER_DB", str(DATA_DIR / "ledger.db"))

# 辩题库：入仓预设（可提交）+ 本机自建（不入仓）
TOPICS_YAML = os.environ.get("TOPICS_YAML", str(ROOT / "configs" / "topics.yaml"))
TOPICS_JSON = os.environ.get("TOPICS_JSON", str(DATA_DIR / "topics.json"))


def upstream_configured() -> bool:
    """上游凭据是否就位（只报布尔，不泄露值）。"""
    return bool(os.environ.get("ANTHROPIC_BASE_URL")) and bool(
        os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
