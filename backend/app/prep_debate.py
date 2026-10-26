"""自动辩论（教学向）：AI 按标准华语辩论流程打完整场，供学习者观察打法。

红线澄清：这是**教学示范**（看 AI 怎么打一场，学环节打法），不是"AI 互搏
竞技评估"——不做胜负判定、不做 Elo、不打分。产品定义（HANDOVER 决策 1-14）
当年排除的"互搏"指的是对抗评估产品；本模块是备赛教学素材的生成器，
每场消耗 10–16 次上游调用，**成本必须在开始前明示**。

流程（与标准赛制一致，反方四辩先于正方四辩）：
    立论陈词×2 → 驳论反驳×2 → 质询与小结×2 → 自由辩论 N轮×2 → 结辩陈词×2

每个环节的发言要求（字数/结构）编码在 PER_STAGE——把"怎么打辩论"的领域
知识写成工程资产。提示词纪律（反幻觉）沿用 SYSTEM_PREP。

停止语义：前端断开（AbortController）→ SSE 生成器被取消 → **当前这一次
发言仍会完成并计费**（线程里的上游调用无法撤回），后续发言不再发起——
界面必须如实告知这一点。
"""
from __future__ import annotations


from .prep import SYSTEM_PREP


def build_flow(rounds: int) -> list[dict]:
    """标准流程：rounds 为自由辩论轮数（2–5），返回发言步骤列表。"""
    rounds = max(2, min(5, int(rounds)))
    flow = [
        {"stage": "立论陈词", "side": "pro", "speaker": "正方一辩"},
        {"stage": "立论陈词", "side": "con", "speaker": "反方一辩"},
        {"stage": "驳论反驳", "side": "pro", "speaker": "正方二辩"},
        {"stage": "驳论反驳", "side": "con", "speaker": "反方二辩"},
        {"stage": "质询与小结", "side": "pro", "speaker": "正方三辩"},
        {"stage": "质询与小结", "side": "con", "speaker": "反方三辩"},
    ]
    for i in range(1, rounds + 1):
        cn = "一二三四五"[i - 1]
        flow.append({"stage": f"自由辩论·第{cn}轮", "side": "pro", "speaker": "正方", "free": True})
        flow.append({"stage": f"自由辩论·第{cn}轮", "side": "con", "speaker": "反方", "free": True})
    flow.append({"stage": "结辩陈词", "side": "con", "speaker": "反方四辩"})
    flow.append({"stage": "结辩陈词", "side": "pro", "speaker": "正方四辩"})
    return flow


#: 每个环节的发言要求——把"怎么打辩论"的领域知识编码成提示词资产
PER_STAGE: dict[str, str] = {
    "立论陈词": "给出本持方的一辩立论：①定义（关键概念一次性讲透）②判准（判断标准）③三个论点（每点=观点句+逻辑链+一个可查证例证）④价值落点。约 280–340 字。",
    "驳论反驳": "针对对方的立论与驳论，点破其核心漏洞至少两处（指明对方原话或逻辑断点），并借机强化本方论点。约 240–300 字。",
    "质询与小结": "先抛出 2–3 个封闭式质询问题，直击对方立论 / 判准 / 论点的致命漏洞；再写一段「质询小结」，收拢本方当前优势、点明对方无法回应之处。约 240–300 字。",
    "自由辩论": "只针对对方上一条自由辩论发言做短促交锋：先一句话点破对方漏洞，再一句话推进本方（可补一个例子）。不要展开长篇论证。约 130–180 字。",
    "结辩陈词": "先「破」：点出对方全场始终未解决的关键问题（用第一/第二）；再「立」：两句话收拢本方论证链；最后价值升华（克制准确，占全文最后三分之一）。约 280–340 字。",
}

_SIDE_LABEL = {"pro": "正方", "con": "反方"}


def build_turn_prompt(topic: str, step: dict, transcript: list[dict]) -> str:
    """组装单次发言的提示词：角色 + 实录 + 本环节要求。"""
    side_label = _SIDE_LABEL[step["side"]]
    lines = [
        f"【角色与硬性要求】{SYSTEM_PREP}",
        "",
        f"【本场辩题】{topic}",
        f"你代表：{step['speaker']}（{side_label}）",
    ]
    lines.append("【辩论实录（至此）】")
    if transcript:
        for t in transcript:
            lines.append(f"{t['speaker']}（{t['stage']}）：{t['text']}")
    else:
        lines.append("（暂无，你是第一个发言的。）")
    lines.append("")
    # 自由辩论带「·第N轮」后缀，查表用基础环节名（提示词要求对每轮一致）
    stage_req = PER_STAGE.get(step["stage"]) or PER_STAGE.get(step["stage"].split("·")[0], "")
    lines.append(f"【本环节：{step['stage']}】{stage_req}")
    lines.append("只输出你这一环节的发言正文，不要写「以下是发言」之类的说明。")
    return "\n".join(lines)
