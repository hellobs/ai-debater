"""解释方法策略师。

为什么需要这一路（来自交接文档第 3.4 节）：
「当法条文义有歧义时，辩论的实质就是争夺解释方法的适用优先性。」
对方用文义解释、我方主张目的解释优先 —— 这是法学辩论最容易出彩、
也最容易被忽略的战场。普通辩论 Agent 不会专门去争这个。

角色指令与任务说明在 `prompts/roles/strategist.txt` 与 `prompts/tasks/strategist.txt`。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import StrategistOut


class StrategistAdvisor(Advisor):
    name = "strategist"
    label = "解释方法策略师"
    kind = "strategy"
    output_model = StrategistOut
