"""领域提示词包：辩题的 `domain` → 用哪一套参谋措辞。

一个包 = `prompts/packs/<name>/{roles,tasks}/<参谋名>.txt` 的一份**自包含**拷贝。
包的目录名与认领的 domain 写在 `configs/prompt-packs.yaml`（可改，不改代码）。

本模块只管**选包**（策略）；把包拼进路径是 `mavis_bridge.render(..., pack=...)` 的事
（机制）。分开的理由与 topics / advisors 两层一样：配置文件是数据，
渲染链路不该知道"法学"这个词存在。

三道口径
--------
- `pack_for_domain(domain)`：判别入口。空 domain 与未认领的 domain 都落默认包。
- `all_packs()`：`preload()` 用它逐个包做启动自检 —— 任何一个包缺模板都当场报错。
- `describe()`：给 `/api/health` 与界面的自述。

配置读不到（文件缺失 / 解析失败）时退化为"只有默认包"，只告警不让平台挂掉
—— 与 `advisors.yaml` / `topics.yaml` 同一处置。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from . import config

logger = logging.getLogger("prompt_packs")

#: 配置整个不可用时的兜底包名。它同时是 `configs/prompt-packs.yaml` 里的 default。
FALLBACK_PACK = "general"


def _load() -> dict:
    """读 `configs/prompt-packs.yaml`，返回规范化的 `{"default": str, "packs": [dict]}`。"""
    path = Path(config.PROMPT_PACKS_YAML)
    raw: list = []
    default = FALLBACK_PACK
    if not path.is_file():
        logger.warning("提示词包配置不存在：%s，退化为只用 %r", path, default)
    else:
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            logger.warning("prompt-packs.yaml 解析失败，退化为只用 %r", default, exc_info=True)
            data = {}
        if isinstance(data, dict):
            candidate = data.get("default")
            if isinstance(candidate, str) and candidate.strip():
                default = candidate.strip()
            raw = data.get("packs") or []
        elif isinstance(data, list):
            raw = data

    packs: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            logger.warning("提示词包条目不是映射，已跳过：%r", item)
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            logger.warning("提示词包缺少 name，已跳过：%r", item)
            continue
        domains = item.get("domains") or []
        if isinstance(domains, str):
            domains = [domains]
        packs.append(
            {
                "name": name,
                "label": str(item.get("label") or name).strip(),
                "hint": str(item.get("hint") or "").strip(),
                "domains": [str(d).strip() for d in domains if str(d).strip()],
            }
        )

    names = [p["name"] for p in packs]
    if not packs:
        logger.warning("提示词包配置里没有可用条目，退化为只用 %r", default)
        packs = [{"name": default, "label": default, "hint": "", "domains": []}]
    elif default not in names:
        logger.warning(
            "默认提示词包 %r 不在 packs 里（有 %s），改用第一个", default, "、".join(names)
        )
        default = names[0]
    return {"default": default, "packs": packs}


_cache: Optional[dict] = None


def _spec() -> dict:
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def reset_cache() -> None:
    """丢掉缓存的配置。测试里换 `PROMPT_PACKS_YAML` 后必须调它。"""
    global _cache
    _cache = None


# --------------------------------------------------------------------------
# 判别
# --------------------------------------------------------------------------
def default_pack() -> str:
    return _spec()["default"]


def all_packs() -> list[str]:
    """所有已配置的包名（启动自检要逐个包检查模板齐不齐）。"""
    return [p["name"] for p in _spec()["packs"]]


def pack_for_domain(domain: str | None) -> str:
    """按辩题领域选包。

    空 domain（自由输入、没选预设辩题）与未被任何包认领的 domain 一律落默认包 ——
    这不是"猜"：默认包的定义就是「不预设学科框架」。
    """
    wanted = (domain or "").strip()
    spec = _spec()
    if wanted:
        for pack in spec["packs"]:
            if wanted in pack["domains"]:
                return pack["name"]
        logger.debug("领域 %r 没有对应的提示词包，落到默认包 %r", wanted, spec["default"])
    return spec["default"]


def label_of(pack: str) -> str:
    """包在界面上显示的名字。包名本身就是未知值时原样返回 —— 不要显示成空。"""
    for item in _spec()["packs"]:
        if item["name"] == pack:
            return item["label"]
    return pack


def describe() -> dict:
    """给 `/api/health` 的自述：有哪些包、哪个是兜底、各自认领哪些领域。"""
    spec = _spec()
    return {
        "default": spec["default"],
        "count": len(spec["packs"]),
        "packs": [dict(p) for p in spec["packs"]],
        "dir": str(Path(config.PROMPT_DIR) / "packs"),
    }


__all__ = [
    "FALLBACK_PACK",
    "all_packs",
    "default_pack",
    "describe",
    "label_of",
    "pack_for_domain",
    "reset_cache",
]
