"""解释方法策略师。

为什么需要这一路（来自交接文档第 3.4 节）：
「当法条文义有歧义时，辩论的实质就是争夺解释方法的适用优先性。」
对方用文义解释、我方主张目的解释优先——这是法学辩论最容易出彩、
也最容易被忽略的战场。普通辩论 Agent 不会专门去争这个。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import StrategistOut


class StrategistAdvisor(Advisor):
    name = "strategist"
    label = "解释方法策略师"
    kind = "strategy"
    output_model = StrategistOut

    directive = (
        "你是法律解释方法策略师。你的唯一职责是识别**解释方法之争**，不做一般性反驳。\n"
        "可选方法：文义解释、体系解释、目的解释、历史解释、合宪性解释。\n"
        "纪律：\n"
        "1. 先判断对方实际依赖的是哪一种方法（看他的论证真正靠什么成立）。\n"
        "2. 再给出我方**应当主张优先**的方法，并说明为什么它应当优先。\n"
        "3. 不要泛泛说'要综合运用各种解释方法'——那是废话，等于放弃争夺。"
    )

    def task_block(self) -> str:
        return (
            "请给出最多 2 个解释方法争夺点，每条填四个字段：\n"
            "- opponent_method：对方主要依赖的方法\n"
            "- opponent_effect：该方法在对方论证里起什么作用（一句话）\n"
            "- our_method：我方应主张优先的方法\n"
            "- counter：为什么我方主张的方法应优先（一句话）"
        )
