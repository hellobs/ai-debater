"""参谋团名册与选择。

名册定义在 `configs/advisors.yaml`（可临时停用某一路，不删定义）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from .auditor import AuditorAdvisor
from .base import Advisor, DebateContext, as_text
from .questioner import QuestionerAdvisor
from .rebutter import RebutterAdvisor
from .. import config

logger = logging.getLogger("advisors")

#: 新参谋加到这里即可（顺序即前端展示顺序）
REGISTRY: dict[str, type[Advisor]] = {
    RebutterAdvisor.name: RebutterAdvisor,
    QuestionerAdvisor.name: QuestionerAdvisor,
    AuditorAdvisor.name: AuditorAdvisor,
}

_DEFAULT_ENABLED = list(REGISTRY.keys())


def load_roster() -> list[Advisor]:
    """读 advisors.yaml，返回启用的参谋实例。文件缺失时全开。"""
    enabled = _DEFAULT_ENABLED
    path = Path(config.ADVISORS_YAML)
    if path.is_file():
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            enabled = [
                item["name"]
                for item in (data.get("advisors") or [])
                if item.get("enabled", True) and item.get("name") in REGISTRY
            ] or _DEFAULT_ENABLED
        except Exception:  # noqa: BLE001
            logger.warning("advisors.yaml 解析失败，改为全部启用", exc_info=True)

    return [REGISTRY[name]() for name in enabled if name in REGISTRY]


__all__ = ["Advisor", "DebateContext", "as_text", "REGISTRY", "load_roster"]
