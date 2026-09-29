"""逻辑审计员：只负责指认对方论证中的逻辑谬误。"""
from __future__ import annotations

from .base import Advisor
from ..schemas import AuditorOut


class AuditorAdvisor(Advisor):
    name = "auditor"
    label = "逻辑审计员"
    kind = "audit"
    output_model = AuditorOut

    directive = (
        "你是逻辑审计员，只负责指认对方论证中的逻辑谬误，不负责反驳。\n"
        "可指认的类型：偷换概念、以偏概全、循环论证、诉诸权威、稻草人、滑坡、"
        "虚假两难、因果倒置。\n"
        "纪律：\n"
        "1. 必须引用对方原话片段作为证据，不许凭空指控。\n"
        "2. 没有发现谬误就返回空列表，**不要为了完成任务而硬找**。"
    )

    def task_block(self) -> str:
        return (
            "请指认对方论证中的谬误，最多 2 条。每条填三个字段：\n"
            "- fallacy：谬误类型\n"
            "- quote：对方原话中最能体现该谬误的片段（不超过30字）\n"
            "- explain：一句话说明谬误所在（不超过60字）\n"
            "没有谬误就返回空列表。"
        )
