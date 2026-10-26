"""备赛 AI 任务（拆题 / 稿件供料 / 成稿）—— 反馈闭环之外的第二个 AI 面。

提示词纪律借鉴「辩论教练」面板并本土化：反幻觉（不编造案例/判例/法条/金额，
不确定用「有报道称」口径）、口语节奏、只输出约定格式。system 指令在本文件
维护一处；调用复用 mavis 的 complete()（经协议桥 → deepseek-flash）。

与参谋分析（/api/analyze）的分工：那边是"场上实时出卡片"（结构化、到点交付），
这边是"备赛桌上出材料"（一篇成稿/一份拆题，无预算硬约束，走默认预算）。
"""
from __future__ import annotations

import json

from pydantic import BaseModel

from .mavis_bridge import bridge_error, complete, is_failed
from .schemas import jsonable

#: system 指令——反幻觉纪律与格式约定（一处维护）
SYSTEM_PREP = (
    "你是「辩手参谋台」的备赛教练，服务华语辩论（BP / 国辩 / 新国辩赛制）备赛。"
    "硬性要求："
    "1. 一切内容必须服务所给辩题与持方，紧扣辩题关键词，绝不答非所问。"
    "2. 严禁编造案例、判例、案号、法条、金额与统计数据；无法核实的细节一律不写，"
    "或改用「有报道称」「据公开研究」口径。"
    "3. 语言要能直接朗读：以短句为主，有辩论现场的口语节奏，避免书面长句与空喊口号。"
    "4. 结构清晰，用 Markdown 小标题与要点列表。"
    "5. 涉及中国大陆法律与政策时，以官方表述为准。"
)


class PrepAIRequest(BaseModel):
    """一次备赛 AI 调用。

    task: split=拆题 / supply=表单供料（JSON） / draft=成稿（Markdown）
    """

    task: str
    topic: str
    side: str = "正方"
    type: str = "auto"              # value / fact / policy / auto
    materials: dict | None = None   # supply/draft 时携带表单既有材料


_TASKS = ("split", "supply", "draft")


def _user_prompt(req: PrepAIRequest) -> str:
    # mavis 的 completion() 只收单个 prompt（无独立 system 位）——
    # 反幻觉纪律折叠在提示词头部，语义等价于 system 指令
    head = f"【角色与硬性要求】{SYSTEM_PREP}\n\n"
    # 拆题是中立分析（要同时给双方主张），不存在"我方"——
    # 带上持方会让模型只写一侧（体检实测：提示词写"我方持方：正方"
    # 却要求 con_claim，输出会偏向正方）
    if req.task == "split":
        head += f"辩题：{req.topic}\n"
    else:
        head += f"辩题：{req.topic}\n我方持方：{req.side}\n"
    if req.task == "split":
        return (
            head
            + "任务：拆题。输出一个 JSON 对象（不要代码围栏），字段："
            "type（value/fact/policy 三选一）、pro_claim（正方主张一句话）、"
            "con_claim（反方主张一句话）、def（正方应做的定义）、std（正方判准）、"
            "clashes（2–3 个核心交锋点，每个=名称+一句话说明）。"
        )
    if req.task == "supply":
        mat = json.dumps(req.materials or {}, ensure_ascii=False)
        return (
            head + f"已有材料（可为空）：{mat}\n"
            "任务：查漏补缺式供料。输出一个 JSON 对象（不要代码围栏），字段："
            "def（定义）、std（判准）、a1/a2/a3（三个论点，每个=观点句+逻辑链+例证）、"
            "quotes（最多 2 句金句）、val（价值落点一句）。只填缺失或明显薄弱的字段，"
            "已有且扎实的字段原样保留。"
        )
    mat = json.dumps(req.materials or {}, ensure_ascii=False)
    return (
        head + f"稿件材料：{mat}\n"
        "任务：把材料展开成可直接朗读的完整辩稿（按材料里的字段顺序成文）。"
        "直接输出稿件正文（Markdown 小标题分节），不要写「以下是稿件」之类的说明。"
    )


def run_prep_ai(req: PrepAIRequest) -> dict:
    """同步执行（调用方放线程池）。返回 {ok, text} 或 {ok: False, error}。"""
    if req.task not in _TASKS:
        return {"ok": False, "error": f"未知任务 {req.task!r}（可选 {'/'.join(_TASKS)}）"}
    if not req.topic.strip():
        return {"ok": False, "error": "辩题为空"}
    out = complete(
        _user_prompt(req),
        retry=2,
        caller=f"prep_{req.task}",
    )
    if is_failed(out):
        return {"ok": False, "error": "上游调用重试耗尽（连接失败或超时），详见 /api/health"}
    err = bridge_error(out)
    if err:
        return {"ok": False, "error": f"协议桥上游失败：{err}"}
    if not isinstance(out, str) or not out.strip():
        return {"ok": False, "error": "模型返回空内容"}
    return {"ok": True, "text": out.strip()}
