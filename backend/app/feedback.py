"""反馈 → 训练数据的导出（闭环的"最后一公里"）。

两类产物，服务两种训练形态：

1. **模仿样本**（双门槛，借鉴 gemma4-learning-agent 并修正其短板）：
   `selected=1`（人工勾选）**且** `rating >= MIN_RATING`（评分线）的参谋产出，
   导出为 OpenAI messages 风格 JSONL。修正的三处：多轮上下文不丢
   （带辩题/立场/对方发言）、按内容哈希去重、各过滤条件的淘汰计数可读。
2. **偏好对**（本项目独有的更强信号）：台账卡片是用户**采纳**的文本，
   与该参谋当时的原始产出做相似度配对——两者不一致时，就是一个
   (rejected=模型原文, chosen=用户采纳版) 偏好对（DPO 类训练的原料）。

全部 0 API 消耗；数据源是本地 SQLite（ledger.db）。
诚实边界：门槛挡得住"没勾选/低分"，挡不住"勾选但内容平庸"——人工勾选
本身就是审核，质量上限取决于使用者的判断。
"""
from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from .ledger import store

#: 人工评分线（与 gemma4 案例同值；CLI 可调）
MIN_RATING = 4
#: 偏好对配对的**错配保底线**（非质量门槛）：低于它说明在同产出里都找不到
#: 哪怕沾边的原文，硬配只会制造噪声。注意用户的真实改笔往往是**大改**
#: （中文短文本 SequenceMatcher 轻易低于 0.5），所以相似度只随 meta 记录、
#: 不作质量判断——成不成对由"是否同源 + 文本是否一致"决定。
PAIR_MATCH_FLOOR = 0.1


def _turn_text(session_id: str) -> str:
    """该会话最近一轮对方发言（训练样本的 user 侧素材）。"""
    turns = store.list_turns(session_id)
    return turns[-1]["opponent_text"] if turns else ""


def _session_meta(session_id: str) -> dict:
    s = store.get_session(session_id)
    return {"topic": s["topic"], "our_side": s["our_side"]} if s else {}


def _latest_per_advisor(session_id: str) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for s in store.list_suggestions(session_id):   # 倒序，先到即最新
        latest.setdefault(s["advisor"], s)
    return latest


def _dedup_key(sample: dict) -> str:
    return hashlib.sha1(
        json.dumps(sample["messages"], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def build_samples(min_rating: int = MIN_RATING) -> tuple[list[dict], dict]:
    """双门槛模仿样本：人工勾选 + 评分线。返回 (样本, 各环节计数)。"""
    counts = {"feedback_rows": 0, "by_rating": 0, "has_payload": 0,
              "nonempty": 0, "unique": 0}
    samples: list[dict] = []
    seen: set[str] = set()

    # 倒序遍历（最新反馈优先）：同内容撞去重键时，保留**最近一次**提交的样本——
    # 否则同素材的旧会话会永久占住去重键，新会话的评分/勾选被静默丢弃
    # （实测咬人：61 行达标反馈去重后只剩最早一条，最新会话的样本凭空消失）。
    for fb in reversed(store.list_feedback()):
        counts["feedback_rows"] += 1
        if not (fb["selected"] and (fb["rating"] or 0) >= min_rating):
            continue
        counts["by_rating"] += 1
        sid, advisor = fb["session_id"], fb["advisor"]
        suggestion = _latest_per_advisor(sid).get(advisor)
        payload = suggestion.get("payload") if suggestion else None
        if not payload:
            continue
        counts["has_payload"] += 1
        meta = _session_meta(sid)
        sample = {
            "messages": [
                {"role": "user",
                 "content": f"辩题：{meta['topic']}\n我方立场：{meta['our_side']}\n"
                            f"对方发言：{_turn_text(sid)}"},
                {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "meta": {"advisor": advisor, "rating": fb["rating"],
                     "session_id": sid},
        }
        counts["nonempty"] += 1
        key = _dedup_key(sample)
        if key in seen:
            continue
        seen.add(key)
        counts["unique"] += 1
        samples.append(sample)
    return samples, counts


def _card_fields(card: dict) -> dict:
    return {k: card.get(k, "") for k in ("claim", "major_premise",
                                         "minor_premise", "conclusion")}


def _item_fields(item: Any) -> dict:
    if isinstance(item, dict):
        return {k: str(item.get(k, "")) for k in ("claim", "major_premise",
                                                  "minor_premise", "conclusion")}
    return {"claim": str(item), "major_premise": "", "minor_premise": "",
            "conclusion": ""}


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def build_pairs(match_floor: float = PAIR_MATCH_FLOOR) -> tuple[list[dict], dict]:
    """偏好对：台账卡片（用户采纳，可能改过笔）vs 参谋原始产出。

    只在文本**不一致**时成对——一致即"原样采纳"，没有偏好信号。
    配对启发式：同 session + 同 advisor（卡片 source）的最新产出里，
    取与卡片主张相似度最高的一条。
    """
    counts = {"cards": 0, "matched": 0, "identical": 0, "pairs": 0}
    pairs: list[dict] = []
    cards_by_session: dict[str, list[dict]] = {}
    for card in store.list_all_cards():
        cards_by_session.setdefault(card["session_id"], []).append(card)

    for sid, cards in cards_by_session.items():
        latest = _latest_per_advisor(sid)
        meta = _session_meta(sid)
        turn = _turn_text(sid)
        for card in cards:
            counts["cards"] += 1
            advisor = card.get("source") or ""
            payload = (latest.get(advisor) or {}).get("payload")
            if not payload or not isinstance(payload, list):
                continue
            chosen = _card_fields(card)
            if not chosen["claim"].strip():
                continue
            best, best_sim = None, 0.0
            for item in payload:
                fields = _item_fields(item)
                sim = _similarity(fields["claim"], chosen["claim"])
                if sim > best_sim:
                    best, best_sim = fields, sim
            if best is None or best_sim < match_floor:
                continue
            counts["matched"] += 1
            if best["claim"].strip() == chosen["claim"].strip():
                counts["identical"] += 1
                continue
            counts["pairs"] += 1
            pairs.append({
                "context": {"topic": meta["topic"], "our_side": meta["our_side"],
                            "opponent_text": turn, "advisor": advisor},
                "chosen": chosen,
                "rejected": best,
                "meta": {"similarity": round(best_sim, 3), "session_id": sid},
            })
    return pairs, counts


def export(out_path: Path, min_rating: int = MIN_RATING,
           include_pairs: bool = True) -> dict:
    """导出 JSONL（模仿样本一行一条；偏好对另写 `*.pairs.jsonl`）。"""
    samples, sample_counts = build_samples(min_rating)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    pairs, pair_counts = [], {"cards": 0}
    if include_pairs:
        pairs, pair_counts = build_pairs()
        pairs_path = out_path.with_suffix(".pairs.jsonl")
        with pairs_path.open("w", encoding="utf-8") as f:
            for p in pairs:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    return {"out": str(out_path), "samples": len(samples),
            "counts": sample_counts, "pairs": len(pairs),
            "pair_counts": pair_counts}
