"""自动辩论（教学向）：AI 按标准华语辩论流程打完整场，供学习者观察打法。

红线澄清：这是**教学示范**（看 AI 怎么打一场，学环节打法），不是"AI 互搏
竞技评估"——不做胜负判定、不做 Elo、不打分。产品定义（HANDOVER 决策 1-14）
当年排除的"互搏"指的是对抗评估产品；本模块是备赛教学素材的生成器，
每场消耗 12–18 次上游调用，**成本必须在开始前明示**。

流程（与标准赛制一致，反方四辩先于正方四辩）：
    立论陈词×2 → 驳论反驳×2 → 质询与小结×2 → 自由辩论 N轮×2 → 结辩陈词×2

每个环节的发言要求（字数/结构）编码在 PER_STAGE——把"怎么打辩论"的领域
知识写成工程资产。提示词纪律（反幻觉）沿用 SYSTEM_PREP。

停止语义：前端断开（AbortController）→ SSE 生成器被取消 → **当前这一次
发言仍会完成并计费**（线程里的上游调用无法撤回），后续发言不再发起——
界面必须如实告知这一点。
"""
from __future__ import annotations


from .mavis_bridge import bridge_error, complete, is_failed
from .prep import SYSTEM_PREP


def build_flow(rounds: int) -> list[dict]:
    """标准流程：rounds 为自由辩论轮数（2–5），返回发言步骤列表。

    质询后插入「半场小结」×2（对齐 2026-10-25 观摩的真实学生赛制：小结是
    独立环节，不是揉在质询里的尾巴）——正方先小结，随即自由辩论开打。
    """
    rounds = max(2, min(5, int(rounds)))
    flow = [
        {"stage": "立论陈词", "side": "pro", "speaker": "正方一辩"},
        {"stage": "立论陈词", "side": "con", "speaker": "反方一辩"},
        {"stage": "驳论反驳", "side": "pro", "speaker": "正方二辩"},
        {"stage": "驳论反驳", "side": "con", "speaker": "反方二辩"},
        {"stage": "质询与小结", "side": "pro", "speaker": "正方三辩"},
        {"stage": "质询与小结", "side": "con", "speaker": "反方三辩"},
        {"stage": "半场小结", "side": "pro", "speaker": "正方三辩"},
        {"stage": "半场小结", "side": "con", "speaker": "反方三辩"},
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
    "半场小结": "只收拢，不开新论：先盘点我方质询的收获（对方承认了什么、答不上什么，用具体问题点名），再点破对方半场始终未解决的一处漏洞，最后一句话预告下半场主攻方向。约 200–260 字。",
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


# --------------------------------------------------------------------------
# 人机对练（教学向）：用户打一方，AI 打另一方，逐环节交互。
#
# 与自动辩论共享 PER_STAGE 环节要求（领域知识单一来源）；区别在于控制权——
# 自动辩论 AI 打全场，对练里用户打一半。每次回应 = 1 次上游调用，界面明示。
# 一期不做胜负判定与评分（产品红线与自动辩论一致）。
# --------------------------------------------------------------------------

def build_sparring_prompt(
    topic: str,
    user_side: str,
    stage: str,
    history: list[dict],
    user_speech: str,
) -> str:
    """组装对练单步提示词。

    user_speech 为空 = AI 先手开局（用户持反方时的立论、或用户想听对方先打）。
    实录里把用户标成「对方辩手」是**AI 的视角**——它要反驳的正是用户。
    """
    user_side = "pro" if user_side == "pro" else "con"
    ai_side = "con" if user_side == "pro" else "pro"
    user_label, ai_label = _SIDE_LABEL[user_side], _SIDE_LABEL[ai_side]

    lines = [
        f"【角色与硬性要求】{SYSTEM_PREP}",
        "",
        f"【本场辩题】{topic}",
        f"你代表：{ai_label}。你的对手（一位真实辩手）代表：{user_label}。",
        "这是人机对练：把对手当真——针对他说过的话打，不要假设他没说过的立场。",
    ]
    lines.append("【实录（至此）】")
    if history:
        for h in history:
            who = user_label if h.get("side") == "user" else ai_label
            lines.append(f"{who}（{h.get('stage') or stage}）：{(h.get('text') or '').strip()}")
    lines.append("")
    if (user_speech or "").strip():
        lines.append(f"{user_label}刚说完（{stage}）：{user_speech.strip()}")
        lines.append(f"请你以{ai_label}身份回应本环节。")
    else:
        lines.append(f"由你先手：请以{ai_label}身份完成本环节发言。")
    if stage.split("·")[0] == "质询与小结":
        # 质询的对练语义按实录状态机拆开：PER_STAGE 的「先抛问题再写小结」是
        # 单人稿结构，直接用在对练上模型会自问自答，用户失去练「被质询时如何接招」的机会。
        # 谁先开口谁是质询方——双向都能练：用户先质询（AI 应答）/ AI 先质询（用户应答）。
        ai_asked = any(
            h.get("side") == "ai" and (h.get("stage") or "").startswith("质询")
            for h in history
        )
        if ai_asked and (user_speech or "").strip():
            lines.append(
                f"对手已回答你的质询（见上）。现在以{ai_label}身份借他的回答追击"
                "（点出矛盾与含糊处），并给出你的质询小结。"
            )
        elif not ai_asked and (user_speech or "").strip():
            lines.append(
                f"对手用质询打你（见上）。你以{ai_label}身份逐条简短应答："
                "先给是/否表态，再补一句理由；确实被问住的点如实承认，"
                "或指出问题本身的前提漏洞。不要长篇展开，不要反过来质询。"
            )
        else:
            lines.append(
                "质询环节对练规则：你只抛出 2–3 个封闭式质询问题，然后停下等对手回答。"
                "此时**不要写质询小结**（小结等对手回答后再做），不要替对手作答，不要自问自答。"
            )
    stage_req = PER_STAGE.get(stage) or PER_STAGE.get(stage.split("·")[0], "")
    lines.append(f"【本环节：{stage}】{stage_req}")
    lines.append("只输出你这一环节的发言正文，不要写「以下是发言」之类的说明。")
    return "\n".join(lines)


def run_sparring(
    topic: str,
    user_side: str,
    stage: str,
    history: list[dict],
    user_speech: str,
) -> dict:
    """同步执行单步对练（调用方放线程池）。返回 {ok, text} 或 {ok: False, error}。"""
    if not topic.strip():
        return {"ok": False, "error": "辩题为空"}
    base_stage = stage.split("·")[0]
    if base_stage not in PER_STAGE:
        return {"ok": False, "error": f"未知环节 {stage!r}（可选 {'/'.join(PER_STAGE)}）"}
    out = complete(
        build_sparring_prompt(topic, user_side, stage, history, user_speech),
        retry=2,
        caller="sparring",
    )
    if is_failed(out):
        return {"ok": False, "error": "上游调用重试耗尽（连接失败或超时），详见 /api/health"}
    err = bridge_error(out)
    if err:
        return {"ok": False, "error": f"协议桥上游失败：{err}"}
    if not isinstance(out, str) or not out.strip():
        return {"ok": False, "error": "模型返回空内容"}
    return {"ok": True, "text": out.strip()}


def build_sparring_review_prompt(topic: str, user_side: str, turns: list[dict]) -> str:
    """对练教练点评提示词。

    立场切换：教练**只评用户**——AI 的发言是陪练素材，评价它没有意义。
    引用原句点评（哪句站住了、哪句被打穿），不给空泛的「要加强论证」。
    """
    user_side = "pro" if user_side == "pro" else "con"
    user_label = _SIDE_LABEL[user_side]
    ai_label = _SIDE_LABEL["con" if user_side == "pro" else "pro"]

    lines = [
        f"【角色与硬性要求】{SYSTEM_PREP}",
        "",
        f"【本场辩题】{topic}",
        f"这是人机对练的实录：{user_label}是学员（你来点评的对象），{ai_label}是 AI 陪练。",
        "你是教练，不是辩手——不要替学员重打一遍，点评他的表现。",
        "",
        "【实录（按顺序）】",
    ]
    for t in turns:
        who = user_label if t.get("side") == "user" else ai_label
        lines.append(f"{who}（{t.get('stage') or ''}）：{(t.get('text') or '').strip()}")
    lines.append("")
    lines.append(
        "任务：点评学员（"
        + user_label
        + "）本场表现。用**评委的四个维度**逐项检视："
        "立场坚持度（是否全场咬死自己的战场、有没有被对方拖去打别的）；"
        "数据可信度（报过的数据经得起基数/口径/来源三问吗——经不起的当场指出）；"
        "回应完整度（对方反复追问的问题有没有正面回应、还是绕开了）；"
        "临场脱稿度（回应是对着场上说的还是像在念预制稿）。"
        "输出 Markdown："
        "「打得最好的」（1–2 处，引用他的原句，说明好在哪）；"
        "「被打穿的」（1–2 处，引用他的原句，说明对方是怎么打穿它的）；"
        "「评委四维体检」（按上面四个维度逐项给结论，引用实录原话作证据）；"
        "「下场改一条」（只给一条，可直接执行）。"
        "全程只依据实录材料，不虚构场上没发生的交锋。"
    )
    return "\n".join(lines)


def run_sparring_review(topic: str, user_side: str, turns: list[dict]) -> dict:
    """对练教练点评（1 次上游调用）。返回 {ok, text} 或 {ok: False, error}。"""
    if not topic.strip():
        return {"ok": False, "error": "辩题为空"}
    spoken = [t for t in turns if (t.get("text") or "").strip()]
    if len(spoken) < 2:
        return {"ok": False, "error": "实录太短（至少各说一句）——先打一个回合再请教练点评"}
    out = complete(
        build_sparring_review_prompt(topic, user_side, spoken),
        retry=2,
        caller="sparring_review",
    )
    if is_failed(out):
        return {"ok": False, "error": "上游调用重试耗尽（连接失败或超时），详见 /api/health"}
    err = bridge_error(out)
    if err:
        return {"ok": False, "error": f"协议桥上游失败：{err}"}
    if not isinstance(out, str) or not out.strip():
        return {"ok": False, "error": "模型返回空内容"}
    return {"ok": True, "text": out.strip()}
