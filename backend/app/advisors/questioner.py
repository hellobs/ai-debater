"""质询手：生成可以立刻向对方抛出的质询问题。"""
from __future__ import annotations

from .base import Advisor
from ..schemas import QuestionerOut


class QuestionerAdvisor(Advisor):
    name = "questioner"
    label = "质询手"
    kind = "questions"
    output_model = QuestionerOut

    directive = (
        "你是我方质询手，负责生成可以立刻向对方抛出的质询问题。\n"
        "纪律：\n"
        "1. 每个问题必须让对方难以两全（承认一边就伤另一边）。\n"
        "2. 只输出问题本身，不加解释、不加铺垫。\n"
        "3. 优先攻击对方论证的前提，而不是他的结论。"
    )

    def task_block(self) -> str:
        return "请给出 3 个质询问题，每个不超过 40 字。"
