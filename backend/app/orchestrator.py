"""参谋编排：并行跑多路参谋，并支持**时间预算**（现场模式的关键）。

为什么是"我方的编排"而不是 mavis 的 Simulator：
阶段 0 已验证 mavis 的 `Simulator` 是"每 tick 让所有 Agent 走生活仿真管线"，
与"并行出主意"语义错位（详见 docs/spike-0-report.md）。

观察者走 mavis 的插件总线
------------------------
结果的消费方（落库 / 推流 / 指标）不再内联在编排逻辑里，而是挂到
`mavisframework.plugin.PluginManager` 上（见 observers.py）。编排只负责
"跑完一路就广播一条事件"，至于谁在听、听的人挂了怎么办，交给总线。

时间预算（budget_s）
--------------------
现场模式下，"全部返回"不如"到点就交付已好的部分"。
超过预算仍未返回的参谋会被标成 `timeout` 并立刻推给前端，
不阻塞其他已经好的结果 —— 用户可以先看能用的，再决定要不要等。
"""
from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import Callable, Iterable, Optional

from . import observers
from .advisors import Advisor, DebateContext
from .mavis_bridge import PluginManager
from .schemas import AdvisorResult

logger = logging.getLogger("orchestrator")

OnResult = Optional[Callable[[AdvisorResult], None]]


def run_advisors(
    ctx: DebateContext,
    advisors: Iterable[Advisor],
    on_result: OnResult = None,
    retry: int = 2,
    budget_s: float | None = None,
    plugins: Optional[PluginManager] = None,
) -> tuple[list[AdvisorResult], float]:
    """并行执行所有参谋，返回（结果列表, 总墙钟秒数）。

    结果按**完成顺序**广播给总线（SSE 用），返回列表按名册顺序稳定排列。
    `budget_s` 为 None 表示不设预算（等到全部返回）。
    `plugins` 给了就用调用方那份（SSE 路径要自己拼 `out_queue` 观察者），
    没给就现搭一个（至少带上进程级指标观察者）。
    """
    advisors = list(advisors)
    started = time.time()
    collected: dict[str, AdvisorResult] = {}

    if not advisors:
        return [], 0.0

    manager = plugins if plugins is not None else observers.build_manager(on_result=on_result)
    if plugins is not None and on_result is not None:
        manager.mount(observers.CallbackPlugin(on_result))
    manager.setup({
        "topic": ctx.topic,
        "our_side": ctx.our_side,
        "advisors": [a.name for a in advisors],
        "budget_s": budget_s,
        "retry": retry,
        "started_at": started,
    })
    manager.emit({
        "type": observers.EVENT_RUN_START,
        "topic": ctx.topic,
        "our_side": ctx.our_side,
        "advisors": [a.name for a in advisors],
        "budget_s": budget_s,
    })

    deadline = started + budget_s if budget_s else None
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(advisors))

    def _emit(result: AdvisorResult) -> None:
        collected[result.advisor] = result
        manager.emit({"type": observers.EVENT_RESULT, "result": result})

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
        total = round(time.time() - started, 2)
        # 不等待仍在跑的线程：现场模式下不能为了收尾再阻塞一次
        pool.shutdown(wait=False)
        # run_end 必须发出去 —— 推流观察者靠它收尾，指标观察者靠它打小结
        manager.emit({"type": observers.EVENT_RUN_END, "total_latency_s": total})
        # teardown 里逐插件的异常同样被总线隔离，不会掩盖上面的结果
        manager.teardown()

    ordered = [collected[a.name] for a in advisors if a.name in collected]
    return ordered, total
