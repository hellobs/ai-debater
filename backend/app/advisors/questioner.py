"""质询手：生成可以立刻向对方抛出的质询问题。

角色指令与任务说明在 `prompts/packs/<包>/roles/questioner.txt` 与 `.../tasks/questioner.txt`。
这一路与领域无关，两个包里的文件逐字节相同（见 README「提示词包」）。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import QuestionerOut


class QuestionerAdvisor(Advisor):
    name = "questioner"
    label = "质询手"
    kind = "questions"
    output_model = QuestionerOut
