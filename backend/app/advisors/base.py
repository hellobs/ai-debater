"""参谋基类。

每个参谋 = 一段角色指令 + 一个输出模型 + 一个结果形状（kind）。
业务逻辑全部在 mavis 之外 —— 这是 mavis 契约测试自己要求的
（框架源码禁止出现业务词汇）。

提示词从哪来
------------
三层，全部是 `.txt` 数据，经 mavis 的模板层（`Scratch.build_prompt`）填充：

    prompts/layout.txt            总装：$directive / $context / $task
    prompts/roles/<name>.txt      角色指令（我是谁、纪律是什么）
    prompts/tasks/<name>.txt      本次任务（要输出什么形状）

以前这些是 Python 里的长中文字符串常量。搬进模板层的收益是它们变成了
**可版本化的数据**：改措辞是一次可 diff 的提交、能逐参谋覆盖、
不需要动代码。代价是 `$` 成了保留字符（`string.Template` 语法）。

唯一留在代码里的是 `context_block()` —— 它有分支（有没有我方台账），
而模板层只会无条件替换，硬塞进去反而更难读。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .. import config, mavis_bridge
from ..mavis_bridge import complete, is_failed
from ..schemas import AdvisorResult, jsonable

logger = logging.getLogger("advisor")


class PromptTemplateError(RuntimeError):
    """提示词模板缺失或无法渲染。启动自检时直接抛，不做静默降级。"""


@dataclass
class DebateContext:
    """一次分析的全部输入。"""

    topic: str
    our_side: str
    opponent_text: str
    our_ledger: list[str] = field(default_factory=list)   # 阶段 3 用：我方已主张


class Advisor:
    #: 代码里的这四个类属性是**默认值**；`configs/advisors.yaml` 可逐路覆盖
    #: label / kind / domain（见 advisors/__init__.py 的 load_roster）。
    name: str = ""
    label: str = ""
    kind: str = "text"
    #: 场景领域。空 = 通用（任何辩题都能上场）；非空 = 该领域专用。
    #: 前端据此在名册里标注「这一路是某个场景专用的」，不做静默替换。
    domain: str = ""
    output_model: Optional[type] = None

    # ------------------------------------------------------------------
    # 名册
    # ------------------------------------------------------------------
    def meta(self) -> dict:
        """名册元数据。前端据此渲染参谋列 —— 免得把名册在前端再抄一份。"""
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "domain": self.domain,
        }

    # ------------------------------------------------------------------
    # 提示词
    # ------------------------------------------------------------------
    def context_block(self, ctx: DebateContext) -> str:
        """本次辩论的运行时事实。代码生成，不走模板（见模块 docstring）。"""
        lines = [f"【辩题】{ctx.topic}", f"【我方立场】{ctx.our_side}"]
        if ctx.our_ledger:
            lines.append("【我方已经主张过】" + "；".join(ctx.our_ledger))
        lines.append(f"【对方刚说】{ctx.opponent_text}")
        return "\n".join(lines)

    def role_directive(self) -> str:
        """角色指令。命名对齐 mavis 里的 `role_directive` 概念。"""
        return mavis_bridge.render(f"roles/{self.name}")

    def task_block(self) -> str:
        """本次任务说明。"""
        return mavis_bridge.render(f"tasks/{self.name}")

    def build_prompt(self, ctx: DebateContext) -> str:
        """三层总装。顺序定义在 `prompts/layout.txt` 里，不在这里。"""
        return mavis_bridge.render(
            "layout",
            {
                "directive": self.role_directive(),
                "context": self.context_block(ctx),
                "task": self.task_block(),
            },
        )

    # ------------------------------------------------------------------
    # 结果规整（作为 mavis `completion(callback=...)` 传进去）
    # ------------------------------------------------------------------
    @staticmethod
    def adapt(out: Any) -> Any:
        """把模型输出归一化：去空白、丢掉整条全空的条目。

        **刻意保守**：只做清洗，不做判分。原因是 mavis 把 callback 返回 `None`
        当成"这次不算数，重试一次"，所以在这里否决内容会把"质量一般"
        放大成 `retry` 倍的上游调用 —— 那是拿真金白银换我们还不确定的好处。
        洗不干净就给空值，由 `run()` 记成 `empty`，代价为零。

        想更严（例如"反驳要点必须四个字段齐"，`Rebuttal` 的 schema 里已经写了
        但模型不一定听）时，先跑一轮真实数据看误杀率，再动这里。
        """
        if out is None:
            return None
        if isinstance(out, str):
            return out.strip()
        if isinstance(out, (list, tuple)):
            items = []
            for item in out:
                if isinstance(item, str):
                    if item.strip():
                        items.append(item.strip())
                elif isinstance(item, dict):
                    cleaned = {
                        k: (v.strip() if isinstance(v, str) else v)
                        for k, v in item.items()
                    }
                    if any(str(v).strip() for v in cleaned.values()):
                        items.append(cleaned)
                elif item is not None:
                    items.append(item)
            return items
        if isinstance(out, dict):
            return {
                k: (v.strip() if isinstance(v, str) else v)
                for k, v in out.items()
            }
        return out

    # ------------------------------------------------------------------
    def run(self, ctx: DebateContext, retry: int = 2) -> AdvisorResult:
        started = time.time()
        try:
            out = complete(
                self.build_prompt(ctx),
                return_type=self.output_model,
                retry=retry,
                caller=self.name,          # → provider 的逐参谋计数
                callback=self.adapt,       # → 结果规范化
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("参谋 %s 调用失败", self.name)
            return AdvisorResult(
                advisor=self.name, label=self.label, status="error",
                latency_s=round(time.time() - started, 2),
                error=repr(exc), kind=self.kind,
            )
        latency = round(time.time() - started, 2)

        if is_failed(out):
            # mavis 把上游异常全吞了（含 90s 超时），只有重试耗尽才走到这
            logger.warning("参谋 %s 上游调用重试耗尽", self.name)
            return AdvisorResult(
                advisor=self.name, label=self.label, status="error",
                latency_s=latency, kind=self.kind,
                error="上游调用重试耗尽（连接失败或超时），详见 /api/health 的 provider summary",
            )

        if out is None or (isinstance(out, (list, str, dict)) and len(out) == 0):
            return AdvisorResult(
                advisor=self.name, label=self.label, status="empty",
                latency_s=latency, kind=self.kind,
            )

        return AdvisorResult(
            advisor=self.name, label=self.label, status="ok",
            latency_s=latency, payload=jsonable(out), kind=self.kind,
        )


# ----------------------------------------------------------------------
# 启动自检
# ----------------------------------------------------------------------
_PRELOADED: set[tuple[str, tuple[str, ...]]] = set()
_PRELOAD_LOCK = threading.Lock()


def preload(advisors: list[Advisor]) -> int:
    """检查每个参谋的三层模板齐不齐、能不能渲染；返回检查过的参谋数。

    为什么要**提前**查，而不是等渲染时报错：模板缺一块的表现是提示词里
    少了一整段角色指令，模型照样会返回一段看起来正常的话。这种降级不报错，
    只会让质量悄悄变差 —— 那是最难发现的一类 bug。宁可开不了机。

    缓存键是（模板目录, 参谋名元组）：同一批参谋对着同一个目录只查一次
    （`load_roster()` 每次请求都会调它），换了目录就重查。
    """
    key = (str(config.PROMPT_DIR), tuple(a.name for a in advisors))
    with _PRELOAD_LOCK:
        if key in _PRELOADED:
            return len(key[1])
        for advisor in advisors:
            for layer in ("roles", "tasks"):
                template = f"{layer}/{advisor.name}"
                if not mavis_bridge.has_template(template):
                    raise PromptTemplateError(
                        f"参谋 {advisor.name!r} 缺提示词模板：{mavis_bridge.template_file(template)}"
                    )
            # 真渲染一次：抓 undefined 占位符（Template.substitute 抛 KeyError）
            # 与编码问题，而不是等到第一次分析请求。
            advisor.role_directive()
            advisor.task_block()
        if advisors:
            mavis_bridge.render(
                "layout", {"directive": "", "context": "", "task": ""}
            )
        _PRELOADED.add(key)
        return len(key[1])


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


__all__ = ["Advisor", "DebateContext", "PromptTemplateError", "as_text", "preload"]
