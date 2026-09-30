"""风险提示员。

对应交接文档「坑 1：立场漂移」与「请求权的薄弱环节」：
参谋团如果只报好消息，用户会在台上被打个措手不及。
这一路的职责是**唱反调** —— 指出对方可能设的陷阱、我方立论的薄弱处。

角色指令与任务说明在 `prompts/packs/<包>/roles/risk.txt` 与 `.../tasks/risk.txt`。
角度 4 在 legal 包里是「法源不稳」、在 general 包里是「依据不稳」。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import RiskOut


class RiskAdvisor(Advisor):
    name = "risk"
    label = "风险提示员"
    kind = "risk"
    output_model = RiskOut
