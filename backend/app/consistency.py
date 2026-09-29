"""立场一致性检测（阶段 3）。

台账的作用不只是"记事"：把"我方已经主张过什么"钉住之后，
就能检测**新生成的建议是否与己方此前立场自相矛盾**——即所谓"立场漂移"。

设计取舍：不放进 `/api/analyze` 的热路径（现场延迟敏感），
而是单独一个端点，由前端在建议返回后再调一次。
"""
from __future__ import annotations

import logging
from pydantic import BaseModel, Field

from .mavis_bridge import complete
from .ledger import store

logger = logging.getLogger("consistency")


class Conflict(BaseModel):
    card_id: str = Field(description="与冲突相关的我方台账条目编号；无法确定时填空字符串")
    card_claim: str = Field(description="我方台账中原本的主张，照抄原文")
    new_claim: str = Field(description="新建议中与之冲突的主张，照抄原文")
    reason: str = Field(description="一句话说明冲突在哪，不超过60字")


class ConsistencyOut(BaseModel):
    res: list[Conflict] = Field(description="冲突清单；没有冲突则返回空列表")


PROMPT = """你是立场一致性审计员。你的唯一职责是找出下面「新建议」中
与「我方已主张」相互冲突的条目。

【我方已主张（台账）】
{ledger}

【新建议】
{new_claims}

判定标准（严格执行）：
1. 只有**实质冲突**才算——即两句话不能同时为真，或后一句否定了前一句的适用范围。
2. 表述不同但方向一致，**不算冲突**（例如"法人作品主体可拟制"与"主体资格不限于自然人"）。
3. 只是补充新论据、新角度，**不算冲突**。
4. 宁可漏报，不可误报。没有实质冲突就返回空列表。"""


def check(session_id: str, new_claims: list[str]) -> list[dict]:
    """返回冲突列表；无台账或无冲突时返回空列表。"""
    cards = store.list_cards(session_id, status="standing")
    claims = [c for c in new_claims if c and c.strip()]
    if not cards or not claims:
        return []

    ledger_text = "\n".join(
        f"[{c['id']}] {c['claim']}"
        + (f"（依据：{c['major_premise']}）" if c.get("major_premise") else "")
        for c in cards
    )
    new_text = "\n".join(f"- {c}" for c in claims)

    try:
        out = complete(
            PROMPT.format(ledger=ledger_text, new_claims=new_text),
            return_type=ConsistencyOut,
            retry=2,
        )
    except Exception:  # noqa: BLE001
        logger.exception("一致性检测调用失败")
        return []

    if not isinstance(out, list):
        return []

    valid_ids = {c["id"] for c in cards}
    result = []
    for item in out:
        d = item if isinstance(item, dict) else getattr(item, "__dict__", {})
        cid = str(d.get("card_id") or "")
        result.append({
            "card_id": cid if cid in valid_ids else "",
            "card_claim": d.get("card_claim", ""),
            "new_claim": d.get("new_claim", ""),
            "reason": d.get("reason", ""),
        })
    return result
