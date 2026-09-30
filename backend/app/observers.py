"""落库 / 推流 / 指标 —— 三个观察者，挂在 mavis 的插件总线上。

为什么用 mavis 的插件总线，而不是继续内联回调：

1. **逐插件错误隔离**。`PluginManager.emit()` 对每个插件单独 try/except，
   一个插件抛错只记 warning，不影响其它插件、也不打断主流程。旧写法是三个
   内联回调串在一个函数体里，指标算错会把落库和推流一起带走。
2. **可发现性**。三个观察者成了有名字（`ledger` / `stream` / `metrics`）、
   有独立生命周期的对象，能在日志里按名字定位，也能被单独测试。
3. 顺带白拿了 mavis 的 `setup / emit / teardown` 生命周期。

注意这里**不是**在仿真 mavis 的 `Simulator`。mavis 的 `emit()` 不校验事件类型
（`validate_message` 只认它自己那七种协议消息），所以我们发自定义事件，
不需要伪造 `time` / `chat_line`。事件形状见下面三个常量。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .ledger import store
from .mavis_bridge import Plugin, PluginManager

logger = logging.getLogger("observers")

#: 本项目自定义的事件类型（mavis 只透传，不解释）
EVENT_RUN_START = "run_start"
EVENT_RESULT = "advisor_result"
EVENT_RUN_END = "run_end"

#: 挂在 mavis 插件总线上的观察者名字（`/api/health` 展示"借了插件总线"时列出来）。
#: 说明这个总线不是空谈：每一个名字都是一个真实挂载的 `Plugin` 子类。
OBSERVER_NAMES = ("ledger", "stream", "metrics")


# ==========================================================================
# 观察者
# ==========================================================================
class LedgerPlugin(Plugin):
    """结果一完成就落库。

    这样 SSE 断线后前端能用快照把已经算好的那几路恢复出来，不必重跑 ——
    这是"现场模式"里最实际的一条保障（断线重连不花钱）。
    """

    name = "ledger"

    def __init__(self, session_id: str):
        self._session_id = session_id
        self.saved = 0

    def on_event(self, evt: dict) -> None:
        if evt.get("type") != EVENT_RESULT:
            return
        store.save_suggestion(self._session_id, evt["result"])
        self.saved += 1


class StreamPlugin(Plugin):
    """把结果推给 SSE 队列。

    `run_end` 时推一条 `advisor: "_done"` 的哨兵，消费端据此收尾。
    """

    name = "stream"

    def __init__(self, out_queue: Any, done_payload: dict):
        self._queue = out_queue
        self._done = done_payload

    def on_event(self, evt: dict) -> None:
        kind = evt.get("type")
        if kind == EVENT_RESULT:
            self._queue.put(evt["result"])
        elif kind == EVENT_RUN_END:
            payload = dict(self._done)
            if evt.get("total_latency_s") is not None:
                payload["latency_s"] = evt["total_latency_s"]
            payload["advisor"] = "_done"
            self._queue.put(payload)


class MetricsPlugin(Plugin):
    """**本进程**的实时计数与异常告警。

    为什么不直接用 `/api/metrics`：那是台账 DB 里的跨会话历史分布，
    答不出"刚才这一轮里是哪一路挂了"。这个观察者盯的是当前进程。

    另外它替运维看一眼日志：非 `ok` 的结果会打 WARNING，`run_end` 打一行
    本轮小结。现场模式下没人盯屏幕时，日志是唯一的线索。
    """

    name = "metrics"

    def __init__(self) -> None:
        self.runs = 0
        self._by_advisor: dict[str, dict[str, int]] = {}
        self.last_run: Optional[dict] = None

    def on_event(self, evt: dict) -> None:
        kind = evt.get("type")
        if kind == EVENT_RUN_START:
            self.runs += 1
            self._started_at = evt
            self.last_run = {
                "advisors": list(evt.get("advisors") or []),
                "budget_s": evt.get("budget_s"),
                "counts": {},
                "total_latency_s": None,
            }
        elif kind == EVENT_RESULT:
            result = evt["result"]
            name = getattr(result, "advisor", "?")
            status = getattr(result, "status", "?")
            bucket = self._by_advisor.setdefault(
                name, {"total": 0, "ok": 0, "empty": 0, "error": 0, "timeout": 0}
            )
            bucket["total"] += 1
            bucket[status] = bucket.get(status, 0) + 1
            if self.last_run is not None and name in self.last_run["advisors"]:
                counts = self.last_run["counts"]
                counts[status] = counts.get(status, 0) + 1
            if status != "ok":
                logger.warning(
                    "参谋 %s 本轮结果为 %s：%s",
                    name, status, getattr(result, "error", None) or "-",
                )
        elif kind == EVENT_RUN_END:
            if self.last_run is not None:
                self.last_run["total_latency_s"] = evt.get("total_latency_s")
                counts = self.last_run["counts"]
                summary = "，".join(f"{k} {v}" for k, v in sorted(counts.items()))
                logger.info(
                    "本轮 %d 路参谋：%s，总耗时 %ss",
                    len(self.last_run["advisors"]), summary or "无结果",
                    self.last_run["total_latency_s"],
                )

    def report(self) -> dict:
        """给 `/api/health` 看的快照。"""
        return {
            "runs": self.runs,
            "by_advisor": self._by_advisor,
            "last_run": self.last_run,
        }


class CallbackPlugin(Plugin):
    """把老式的 `on_result` 回调适配成插件。

    存在的意义是让 `run_advisors()` 只需要维护**一条**广播路径
    （插件总线），而不用同时保留"直接回调"和"总线"两套。
    """

    name = "callback"

    def __init__(self, fn: Callable[[Any], None]):
        self._fn = fn

    def on_event(self, evt: dict) -> None:
        if evt.get("type") == EVENT_RESULT:
            self._fn(evt["result"])


#: 进程级指标观察者。每次分析都会挂上去，`/api/health` 读它。
PROCESS_METRICS = MetricsPlugin()


def build_manager(
    *,
    session_id: Optional[str] = None,
    out_queue: Any = None,
    done_payload: Optional[dict] = None,
    on_result: Optional[Callable[[Any], None]] = None,
    plugins: Optional[list[Plugin]] = None,
) -> PluginManager:
    """把"这次分析要哪些观察者"拼成一个 `PluginManager`。

    只传需要的部件：SSE 路径给 `out_queue`，一次性路径给 `on_result`。
    进程级的 `PROCESS_METRICS` 总是挂上。
    """
    mounted: list[Plugin] = []
    if session_id:
        mounted.append(LedgerPlugin(session_id))
    if out_queue is not None and done_payload is not None:
        mounted.append(StreamPlugin(out_queue, done_payload))
    if on_result is not None:
        mounted.append(CallbackPlugin(on_result))
    mounted.append(PROCESS_METRICS)
    if plugins:
        mounted.extend(plugins)
    return PluginManager(mounted)


__all__ = [
    "EVENT_RESULT",
    "EVENT_RUN_END",
    "EVENT_RUN_START",
    "OBSERVER_NAMES",
    "CallbackPlugin",
    "LedgerPlugin",
    "MetricsPlugin",
    "PROCESS_METRICS",
    "StreamPlugin",
    "build_manager",
]
