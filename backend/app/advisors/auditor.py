"""逻辑审计员：只负责指认对方论证中的逻辑谬误。

角色指令与任务说明在 `prompts/roles/auditor.txt` 与 `prompts/tasks/auditor.txt`。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import AuditorOut


class AuditorAdvisor(Advisor):
    name = "auditor"
    label = "逻辑审计员"
    kind = "audit"
    output_model = AuditorOut
