"""辩题库：入仓预设（`configs/topics.yaml`）+ 本机自建（`data/topics.json`）。

为什么要有这一层
----------------
此前辩题是前端 `App.tsx` 里一个写死的常量，只能手输、无法预置、无法跨会话复用。
现场备赛的真实用法是：**辩题提前定好，立场随之确定**，到场上只剩把对方的话打进去。
所以辩题要能提前配置 —— 并且要能整条带走（含双方立场与对方例句）。

单一来源
--------
- `configs/topics.yaml`：入仓预设辩题库。手写 YAML 即「提前配置」，团队共享。
- `data/topics.json`：本机自建辩题，**不入仓**（与 `ledger.db` / `corpus` 同一约定）。
- 运行时**并集**返回；同 id 时本机覆盖预设（便于不改仓库就微调预设文案）。

这里刻意**不内置任何兜底辩题**：库为空就返回空，前端退化为纯自由输入。
兜底等于把辩题定义在第二个地方 —— 正是本项目要消灭的那种重复。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config

logger = logging.getLogger("topics")

#: 预设辩题的默认场景分组
DEFAULT_DOMAIN = "通用"
#: 从界面保存的辩题统一归到这一组，便于与入仓预设区分
LOCAL_DOMAIN = "我的辩题"

#: 允许出现在 URL 路径里的 id 形状（`DELETE /api/topics/{id}` 依赖它）
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass
class Topic:
    """一条辩题。

    双方立场是辩题的**一部分**，不是并列的独立配置 ——
    「控方（主张应享有）」脱离「AI 生成内容是否应享有著作权」就没有意义。
    """

    id: str
    title: str
    domain: str = DEFAULT_DOMAIN
    side_a: str = "正方"
    side_b: str = "反方"
    #: 对方最可能的第一句话。既是「对方刚说」的一键填充，也是示例文案的来源。
    opponent_hint: str = ""
    #: 一句话争点说明（可选）
    note: str = ""
    #: preset = 入仓预设；local = 本机自建（可删除）
    source: str = "preset"

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# 解析与规范化
# --------------------------------------------------------------------------
def _auto_id(title: str) -> str:
    """本地辩题的自动 id：标题的稳定短哈希。

    同一标题重复保存会得到同一个 id → 覆盖而不是堆重复，
    同时避免把中文塞进 URL 路径。
    """
    digest = hashlib.sha1(title.strip().encode("utf-8")).hexdigest()[:8]
    return f"local-{digest}"


def _clean_id(raw: str, title: str) -> str:
    """id 合法就用它，否则按标题生成。"""
    candidate = (raw or "").strip().lower()
    if candidate and _ID_RE.match(candidate):
        return candidate
    if candidate:
        logger.warning("辩题 id 不合法（%r），改为按标题生成", raw)
    return _auto_id(title)


def _coerce(item: object, source: str) -> Topic | None:
    """把 YAML/JSON 里的一条原始数据规范成 Topic。缺 title 的条目跳过。"""
    if not isinstance(item, dict):
        logger.warning("辩题条目不是映射，已跳过：%r", item)
        return None

    title = str(item.get("title") or "").strip()
    if not title:
        logger.warning("辩题缺少 title，已跳过：%r", item)
        return None

    def _text(key: str) -> str:
        return str(item.get(key) or "").strip()

    return Topic(
        id=_clean_id(_text("id"), title),
        title=title,
        domain=_text("domain") or DEFAULT_DOMAIN,
        side_a=_text("side_a") or "正方",
        side_b=_text("side_b") or "反方",
        opponent_hint=_text("opponent_hint"),
        note=_text("note"),
        source=source,
    )


# --------------------------------------------------------------------------
# 读取
# --------------------------------------------------------------------------
def _read_presets() -> list[Topic]:
    path = Path(config.TOPICS_YAML)
    if not path.is_file():
        logger.warning("预设辩题库不存在：%s（只剩自由输入与本机辩题）", path)
        return []
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        logger.warning("topics.yaml 解析失败，预设辩题不可用", exc_info=True)
        return []

    items = data.get("topics") if isinstance(data, dict) else data
    if not isinstance(items, list):
        logger.warning("topics.yaml 里没有 topics 列表，预设辩题不可用")
        return []
    out = [t for t in (_coerce(i, "preset") for i in items) if t]
    logger.debug("预设辩题 %d 条", len(out))
    return out


def _read_local() -> list[Topic]:
    path = Path(config.TOPICS_JSON)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("topics.json 解析失败，本机辩题不可用", exc_info=True)
        return []

    items = data.get("topics") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [t for t in (_coerce(i, "local") for i in items) if t]


def load_topics() -> list[Topic]:
    """预设 + 本机，按 id 去重（本机覆盖预设）。

    顺序：预设按 YAML 书写顺序在前，本机新增的追加在后
    —— 前端因此不需要额外排序逻辑，分组顺序即配置顺序。
    """
    merged: dict[str, Topic] = {}
    for topic in _read_presets():
        merged[topic.id] = topic
    for topic in _read_local():
        merged[topic.id] = topic
    return list(merged.values())


# --------------------------------------------------------------------------
# 写入（只碰本机那份，永不改入仓预设）
# --------------------------------------------------------------------------
def _write_local(items: list[Topic]) -> None:
    """原子写：先落临时文件再 replace，避免中途失败留下半截 JSON。"""
    path = Path(config.TOPICS_JSON)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"topics": [t.to_dict() for t in items]}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def save_local_topic(
    title: str,
    *,
    topic_id: str | None = None,
    domain: str = "",
    side_a: str = "",
    side_b: str = "",
    opponent_hint: str = "",
    note: str = "",
) -> Topic:
    """保存（或按 id 覆盖）一条本机辩题，返回落库后的对象。

    `title` 为空抛 `ValueError` —— 空辩题没有任何用途，不如直接拒绝。
    """
    title = (title or "").strip()
    if not title:
        raise ValueError("辩题内容不能为空")

    topic = Topic(
        id=_clean_id((topic_id or "").strip().lower(), title),
        title=title,
        domain=(domain or "").strip() or LOCAL_DOMAIN,
        side_a=(side_a or "").strip() or "正方",
        side_b=(side_b or "").strip() or "反方",
        opponent_hint=(opponent_hint or "").strip(),
        note=(note or "").strip(),
        source="local",
    )

    items = [t for t in _read_local() if t.id != topic.id]
    items.append(topic)
    _write_local(items)
    logger.info("已保存本机辩题 %s（%s）", topic.id, topic.title)
    return topic


def delete_local_topic(topic_id: str) -> bool:
    """删除一条本机辩题。预设删不掉（返回 False）。"""
    tid = (topic_id or "").strip().lower()
    if not tid:
        return False
    items = _read_local()
    kept = [t for t in items if t.id != tid]
    if len(kept) == len(items):
        return False
    _write_local(kept)
    logger.info("已删除本机辩题 %s", tid)
    return True


__all__ = ["Topic", "DEFAULT_DOMAIN", "LOCAL_DOMAIN", "load_topics",
           "save_local_topic", "delete_local_topic"]
