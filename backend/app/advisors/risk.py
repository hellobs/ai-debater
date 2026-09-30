"""风险提示员。

对应交接文档「坑 1：立场漂移」与「请求权的薄弱环节」：
参谋团如果只报好消息，用户会在台上被打个措手不及。
这一路的职责是**唱反调**——指出对方可能设的陷阱、我方立论的薄弱处。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import RiskOut


class RiskAdvisor(Advisor):
    name = "risk"
    label = "风险提示员"
    kind = "risk"
    output_model = RiskOut

    directive = (
        "你是风险提示员，职责是**唱反调**：不提供反驳，只指出风险。\n"
        "必须覆盖的角度：\n"
        "1. 对方可能设的陷阱（例如诱导我方承认某个前提）；\n"
        "2. 我方立论中最薄弱、最可能被追问的环节；\n"
        "3. 事实层面尚未查清、一旦被追问就答不上来的点；\n"
        "4. 法源不稳之处（引用可能站不住、或与上位法冲突）。\n"
        "纪律：宁可说出让人不舒服的风险，也不要报喜不报忧；"
        "但不要编造风险，没有就把对应类型略过。"
    )

    def task_block(self) -> str:
        return (
            "请给出最多 3 条风险，每条填三个字段：\n"
            "- risk：风险点（一句话，不超过40字）\n"
            "- kind：风险类型（对方陷阱 / 我方薄弱 / 事实不清 / 法源不稳）\n"
            "- suggestion：一句话应对建议（不超过40字）"
        )
