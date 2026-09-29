"""参谋编排：并行跑多路参谋。

为什么是"我方的编排"而不是 mavis 的 Simulator：
阶段 0 已验证 mavis 的 `Simulator` 是"每 tick 让所有 Agent 走生活仿真管线"，
与"并行出主意"语义错位（详见 docs/spike-0-report.md）。
"""
from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import Callable, Iterable, Optional

from .advisors import Advisor, DebateContext
from .schemas import AdvisorResult

logger = logging.getLogger("orchestrator")

OnResult = Optional[Callable[[AdvisorResult], None]]


def run_advisors(
    ctx: DebateContext,
    advisors: Iterable[Advisor],
    on_result: OnResult = None,
    retry: int = 2,
) -> tuple[list[AdvisorResult], float]:
    """并行执行所有参谋，返回（结果列表, 总墙钟秒数）。

    结果按**完成顺序**回调 `on_result`（SSE 用），但返回列表按名册顺序稳定排列。
    """
    advisors = list(advisors)
    started = time.time()
    collected: dict[str, AdvisorResult] = {}

    if not advisors:
        return [], 0.0

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(advisors)) as pool:
        futures = {pool.submit(a.run, ctx, retry): a for a in advisors}
        for future in concurrent.futures.as_completed(futures):
            advisor = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.exception("参谋 %s 异常", advisor.name)
                result = AdvisorResult(
                    advisor=advisor.name, label=advisor.label, status="error",
                    latency_s=0.0, error=repr(exc), kind=advisor.kind,
                )
            collected[advisor.name] = result
            if on_result:
                try:
                    on_result(result)
                except Exception:  # noqa: BLE001
                    logger.warning("on_result 回调失败", exc_info=True)

    ordered = [collected[a.name] for a in advisors if a.name in collected]
    return ordered, round(time.time() - started, 2)
