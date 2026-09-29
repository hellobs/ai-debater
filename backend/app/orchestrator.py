"""参谋编排：并行跑多路参谋，并支持**时间预算**（现场模式的关键）。

为什么是"我方的编排"而不是 mavis 的 Simulator：
阶段 0 已验证 mavis 的 `Simulator` 是"每 tick 让所有 Agent 走生活仿真管线"，
与"并行出主意"语义错位（详见 docs/spike-0-report.md）。

时间预算（budget_s）
--------------------
现场模式下，"全部返回"不如"到点就交付已好的部分"。
超过预算仍未返回的参谋会被标成 `timeout` 并立刻推给前端，
不阻塞其他已经好的结果——用户可以先看能用的，再决定要不要等。
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
    budget_s: float | None = None,
) -> tuple[list[AdvisorResult], float]:
    """并行执行所有参谋，返回（结果列表, 总墙钟秒数）。

    结果按**完成顺序**回调 `on_result`（SSE 用），返回列表按名册顺序稳定排列。
    `budget_s` 为 None 表示不设预算（等到全部返回）。
    """
    advisors = list(advisors)
    started = time.time()
    collected: dict[str, AdvisorResult] = {}

    if not advisors:
        return [], 0.0

    deadline = started + budget_s if budget_s else None
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(advisors))

    def _emit(result: AdvisorResult) -> None:
        collected[result.advisor] = result
        if on_result:
            try:
                on_result(result)
            except Exception:  # noqa: BLE001
                logger.warning("on_result 回调失败", exc_info=True)

    try:
        futures = {pool.submit(a.run, ctx, retry): a for a in advisors}
        pending = set(futures)

        while pending:
            timeout = None
            if deadline is not None:
                timeout = max(0.0, deadline - time.time())
            done, pending = concurrent.futures.wait(
                pending, timeout=timeout,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if not done:
                break  # 预算耗尽
            for future in done:
                advisor = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    logger.exception("参谋 %s 异常", advisor.name)
                    result = AdvisorResult(
                        advisor=advisor.name, label=advisor.label, status="error",
                        latency_s=0.0, error=repr(exc), kind=advisor.kind,
                    )
                _emit(result)

        # 预算耗尽仍未有结果的，标 timeout 并立刻交付
        for future in pending:
            advisor = futures[future]
            waited = round(time.time() - started, 2)
            _emit(AdvisorResult(
                advisor=advisor.name, label=advisor.label, status="timeout",
                latency_s=waited, kind=advisor.kind,
                error=f"超过 {budget_s:g}s 预算仍未返回",
            ))
    finally:
        # 不等待仍在跑的线程：现场模式下不能为了收尾再阻塞一次
        pool.shutdown(wait=False)

    ordered = [collected[a.name] for a in advisors if a.name in collected]
    return ordered, round(time.time() - started, 2)
