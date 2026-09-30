"""反驳手：针对对方发言给出可直接使用的反驳要点（涵摄三段式）。

角色指令与任务说明在 `prompts/roles/rebutter.txt` 与 `prompts/tasks/rebutter.txt`。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import RebutterOut


class RebutterAdvisor(Advisor):
    name = "rebutter"
    label = "反驳手"
    kind = "rebuttal"
    output_model = RebutterOut
