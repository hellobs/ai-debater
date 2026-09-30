"""参谋团名册与选择。

名册定义在 `configs/advisors.yaml`：可以逐路覆盖 `label` / `kind` / `domain`，
也可以用 `enabled: false` 临时停用某一路（定义保留在代码里）。
**列表顺序即前端展示顺序** —— 改顺序就是挪行，不再需要额外的 order 字段。

代码里的类属性（`advisors/*.py`）是默认值，YAML 是覆盖层。
前端不再重复定义名册，改为读 `/api/health` 返回的元数据。
"""
from __future__ import annotations

import logging
from pathlib import Path

from .auditor import AuditorAdvisor
from .base import Advisor, DebateContext, as_text
from .questioner import QuestionerAdvisor
from .rebutter import RebutterAdvisor
from .risk import RiskAdvisor
from .strategist import StrategistAdvisor
from .. import config

logger = logging.getLogger("advisors")

#: 新参谋加到这里即可（无 YAML 时的默认顺序）
REGISTRY: dict[str, type[Advisor]] = {
    RebutterAdvisor.name: RebutterAdvisor,
    QuestionerAdvisor.name: QuestionerAdvisor,
    AuditorAdvisor.name: AuditorAdvisor,
    StrategistAdvisor.name: StrategistAdvisor,
    RiskAdvisor.name: RiskAdvisor,
}

#: 允许被 YAML 覆盖的元数据字段
_OVERRIDABLE = ("label", "kind", "domain")


def _read_specs() -> list[dict]:
    """读 advisors.yaml 里的条目。文件缺失/解析失败返回空列表（由调用方决定兜底）。"""
    path = Path(config.ADVISORS_YAML)
    if not path.is_file():
        logger.warning("参谋名册不存在：%s，改为全部启用默认值", path)
        return []
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        logger.warning("advisors.yaml 解析失败，改为全部启用默认值", exc_info=True)
        return []

    items = data.get("advisors") if isinstance(data, dict) else data
    if not isinstance(items, list):
        logger.warning("advisors.yaml 里没有 advisors 列表，改为全部启用默认值")
        return []
    return [i for i in items if isinstance(i, dict)]


def _instantiate(name: str, spec: dict) -> Advisor:
    """实例化一路参谋，并用 YAML 里显式给的非空字符串覆盖默认元数据。"""
    advisor = REGISTRY[name]()
    for field_name in _OVERRIDABLE:
        value = spec.get(field_name)
        if isinstance(value, str) and value.strip():
            setattr(advisor, field_name, value.strip())
    return advisor


def _default_roster() -> list[Advisor]:
    """代码默认名册：REGISTRY 的书写顺序，全部启用、全用类属性默认值。"""
    return [cls() for cls in REGISTRY.values()]


def load_roster() -> list[Advisor]:
    """返回启用的参谋实例，顺序即 YAML 书写顺序。

    判断规则只有一条：**名册里有没有一条能被识别的条目**。

    - 一条都没有（文件缺失 / 解析失败 / 名字全写错）→ 回到代码默认：全部启用，只告警。
      理由：配置整个不可用时，不该连带让平台不可用。
    - 有可识别的条目、但都被 `enabled: false` 停用 → **返回空**。
      理由：这是显式意图。静默改回"全开"会在用户不知情时多花五次上游调用。

    这两种情况的处置是相反的，所以必须分开判断，不能只看"结果是不是空"。
    """
    specs = _read_specs()
    if not specs:
        return _default_roster()

    roster: list[Advisor] = []
    seen: set[str] = set()
    for spec in specs:
        name = spec.get("name")
        if name in seen:
            logger.warning("advisors.yaml 里 %r 重复出现，只取第一条", name)
            continue
        if name not in REGISTRY:
            logger.warning("advisors.yaml 里的 %r 没有对应实现，已忽略", name)
            continue
        seen.add(name)
        if not spec.get("enabled", True):
            continue
        roster.append(_instantiate(name, spec))

    if not seen:
        logger.warning("advisors.yaml 里没有一条能识别的参谋，改为全部启用默认值")
        return _default_roster()
    if not roster:
        logger.warning("advisors.yaml 把所有参谋都停用了，本次不跑任何一路")
    return roster


__all__ = ["Advisor", "DebateContext", "as_text", "REGISTRY", "load_roster"]
