"""质询手：生成可以立刻向对方抛出的质询问题。

角色指令与任务说明在 `prompts/roles/questioner.txt` 与 `prompts/tasks/questioner.txt`。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import QuestionerOut


class QuestionerAdvisor(Advisor):
    name = "questioner"
    label = "质询手"
    kind = "questions"
    output_model = QuestionerOut
