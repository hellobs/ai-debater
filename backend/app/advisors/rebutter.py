"""反驳手：针对对方发言给出可直接使用的反驳要点（四段式三段论）。

角色指令与任务说明在 `prompts/packs/<包>/roles/rebutter.txt` 与 `.../tasks/rebutter.txt`。
「大前提」在 legal 包里是法律规范、在 general 包里是公认原则 —— 两套措辞各写在各自包里。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import RebutterOut


class RebutterAdvisor(Advisor):
    name = "rebutter"
    label = "反驳手"
    kind = "rebuttal"
    output_model = RebutterOut
