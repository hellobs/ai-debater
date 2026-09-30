"""逻辑审计员：只负责指认对方论证中的逻辑谬误。

角色指令与任务说明在 `prompts/packs/<包>/roles/auditor.txt` 与 `.../tasks/auditor.txt`。
这一路与领域无关，两个包里的文件逐字节相同（见 README「提示词包」）。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import AuditorOut


class AuditorAdvisor(Advisor):
    name = "auditor"
    label = "逻辑审计员"
    kind = "audit"
    output_model = AuditorOut
