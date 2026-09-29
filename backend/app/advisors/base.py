"""参谋基类。

每个参谋 = 一段角色指令 + 一个输出模型 + 一个结果形状（kind）。
业务逻辑全部在 mavis 之外——这是 mavis 契约测试自己要求的
（框架源码禁止出现业务词汇）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..mavis_bridge import complete
from ..schemas import AdvisorResult, jsonable

logger = logging.getLogger("advisor")


@dataclass
class DebateContext:
    """一次分析的全部输入。"""

    topic: str
    our_side: str
    opponent_text: str
    our_ledger: list[str] = field(default_factory=list)   # 阶段 3 用：我方已主张


class Advisor:
    name: str = ""
    label: str = ""
    kind: str = "text"
    output_model: Optional[type] = None
    #: 角色指令（会作为提示词的角色块；对应 mavis 里的 role_directive 概念）
    directive: str = ""

    # ------------------------------------------------------------------
    def context_block(self, ctx: DebateContext) -> str:
        lines = [f"【辩题】{ctx.topic}", f"【我方立场】{ctx.our_side}"]
        if ctx.our_ledger:
            lines.append("【我方已经主张过】" + "；".join(ctx.our_ledger))
        lines.append(f"【对方刚说】{ctx.opponent_text}")
        return "\n".join(lines)

    def task_block(self) -> str:
        raise NotImplementedError

    def build_prompt(self, ctx: DebateContext) -> str:
        return (
            f"{self.directive}\n\n"
            f"{self.context_block(ctx)}\n\n"
            f"{self.task_block()}"
        )

    # ------------------------------------------------------------------
    def run(self, ctx: DebateContext, retry: int = 2) -> AdvisorResult:
        started = time.time()
        try:
            out = complete(self.build_prompt(ctx), return_type=self.output_model, retry=retry)
        except Exception as exc:  # noqa: BLE001
            logger.exception("参谋 %s 调用失败", self.name)
            return AdvisorResult(
                advisor=self.name, label=self.label, status="error",
                latency_s=round(time.time() - started, 2),
                error=repr(exc), kind=self.kind,
            )
        latency = round(time.time() - started, 2)

        if out is None or (isinstance(out, (list, str, dict)) and len(out) == 0):
            return AdvisorResult(
                advisor=self.name, label=self.label, status="empty",
                latency_s=latency, kind=self.kind,
            )

        return AdvisorResult(
            advisor=self.name, label=self.label, status="ok",
            latency_s=latency, payload=jsonable(out), kind=self.kind,
        )


def as_text(result: AdvisorResult) -> str:
    """把结果摊平成可读文本（用于导出与日志）。"""
    p = result.payload
    if p is None:
        return ""
    if isinstance(p, str):
        return p
    if isinstance(p, list):
        parts = []
        for i, item in enumerate(p, 1):
            if isinstance(item, dict):
                parts.append(f"{i}. " + " | ".join(f"{k}: {v}" for k, v in item.items()))
            else:
                parts.append(f"{i}. {item}")
        return "\n".join(parts)
    return str(p)


__all__ = ["Advisor", "DebateContext", "as_text", "Any"]
