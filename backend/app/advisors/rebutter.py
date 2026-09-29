"""反驳手：针对对方发言给出可直接使用的反驳要点（涵摄三段式）。"""
from __future__ import annotations

from .base import Advisor
from ..schemas import RebutterOut


class RebutterAdvisor(Advisor):
    name = "rebutter"
    label = "反驳手"
    kind = "rebuttal"
    output_model = RebutterOut

    directive = (
        "你是我方首席反驳手，只输出可以直接照着讲的反驳要点。\n"
        "纪律：\n"
        "1. 每条反驳必须走法律涵摄结构——大前提（法律规范）、小前提（本题事实）、结论（法律效果）。\n"
        "2. 大前提必须精确到条款项。**不确定出处就写「待核验」，绝不编造法条编号或判例。**\n"
        "3. 针对对方论证的具体环节，不要复述对方原话，不要空话。\n"
        "4. 严禁出现「对方也有道理」「我同意对方」这类附和表述。"
    )

    def task_block(self) -> str:
        return (
            "请给出 2 条反驳要点。每条都必须填满四个字段：\n"
            "- claim：主句（一句话，不超过40字）\n"
            "- major_premise：大前提（法条名称+条款号；不确定就写「待核验」并简述规范内容）\n"
            "- minor_premise：小前提（本题事实层面）\n"
            "- conclusion：结论（由大小前提推出的法律效果）"
        )
