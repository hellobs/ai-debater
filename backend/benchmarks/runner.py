"""回归测试集与自动评估（对应交接文档「坑 5：评估缺位」）。

设计原则：**能自动算的指标一律不消耗 API。**

- 格式合规 / 三段论完整性 / 引用核验 / 延迟分布 —— 全部从已有的参谋产出与本地语料算出，
  **零 API 消耗**（`evaluate` / `check` 命令）；
- 真正要跑模型的是 `run --live`，它必须显式确认，并且启动前会把预计调用量打出来。

这样才能回答那个关键问题：**改动是让结果变好了，还是只是变长了？**
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.ledger import store
from app.retrieval import get_retriever, verify_text

logger = logging.getLogger("benchmarks")

ROOT = Path(__file__).resolve().parents[2]          # 仓库根
CASES_DIR = ROOT / "benchmarks" / "cases"
RESULTS_DIR = ROOT / "benchmarks" / "results"

REQUIRED_CASE_FIELDS = ("id", "topic", "our_side", "opponent_text")

#: 各路参谋产出里，"一项建议"应该具备的字段
REBUTTAL_FIELDS = ("claim", "major_premise", "minor_premise", "conclusion")
ITEM_LIST_ADVISORS = {"rebutter", "questioner", "auditor", "strategist", "risk"}


# --------------------------------------------------------------------------
# 用例加载（0 消耗）
# --------------------------------------------------------------------------
def load_cases() -> list[dict]:
    cases: list[dict] = []
    if not CASES_DIR.is_dir():
        return cases
    for path in sorted(CASES_DIR.glob("*.yaml")) + sorted(CASES_DIR.glob("*.yml")):
        try:
            import yaml
        except ImportError:  # pragma: no cover
            logger.error("需要 pyyaml 才能读取用例")
            return cases
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for case in data.get("cases", []):
            case.setdefault("source", str(path.relative_to(ROOT)))
            cases.append(case)
    return cases


def validate_cases(cases: Optional[list[dict]] = None) -> list[str]:
    """用例自身的静态校验（0 消耗）。"""
    cases = cases if cases is not None else load_cases()
    errors: list[str] = []
    seen: set[str] = set()
    for i, case in enumerate(cases):
        prefix = f"[case:{case.get('id', i)}]"
        for f in REQUIRED_CASE_FIELDS:
            if not str(case.get(f, "")).strip():
                errors.append(f"{prefix} 缺少或为空的字段 '{f}'")
        cid = case.get("id")
        if cid:
            if cid in seen:
                errors.append(f"{prefix} id 重复：{cid}")
            seen.add(cid)
        if case.get("opponent_text") and len(str(case["opponent_text"])) < 10:
            errors.append(f"{prefix} opponent_text 过短，不像一段真实发言")
    return errors


# --------------------------------------------------------------------------
# 评估（0 消耗）
# --------------------------------------------------------------------------
def _flatten(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return "\n".join(_flatten(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return "\n".join(_flatten(v) for v in obj)
    return str(obj)


def _latest_per_advisor(suggestions: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for s in suggestions:                      # 倒序存放，取每个 advisor 的第一条即最新
        latest.setdefault(s["advisor"], s)
    return latest


def _case_by_topic(topic: str) -> Optional[dict]:
    for c in load_cases():
        if c.get("topic") == topic:
            return c
    return None


def _focus_coverage(text: str, focus: list[str]) -> dict:
    """要点覆盖率：用例声明的 focus 关键词里，有多少在产出中出现过。

    ⚠️ 这是**粗信号**：它只能回答"这个话题有没有被碰到"，
    不能回答"论证好不好"。别把它当质量分用。
    """
    keywords = [f for f in (focus or []) if str(f).strip()]
    if not keywords:
        return {"hits": 0, "total": 0, "rate": None, "missed": []}
    hit = [k for k in keywords if k in text]
    missed = [k for k in keywords if k not in text]
    return {
        "hits": len(hit),
        "total": len(keywords),
        "rate": round(len(hit) / len(keywords), 3),
        "missed": missed,
    }


def evaluate(session_id: str) -> dict:
    """从已有产出算指标。**不调用任何 LLM。**"""
    snap = store.snapshot(session_id)
    if not snap:
        return {"error": "session not found", "session_id": session_id}

    latest = _latest_per_advisor(snap.get("suggestions", []))
    advisor_stats: dict[str, dict] = {}
    health = {"ok": 0, "timeout": 0, "error": 0, "empty": 0}
    texts: list[str] = []

    for name, s in latest.items():
        payload = s.get("payload")
        status = s.get("status") or "empty"
        health[status] = health.get(status, 0) + 1
        items = len(payload) if isinstance(payload, list) else (1 if payload else 0)
        advisor_stats[name] = {
            "status": status,
            "latency_s": s.get("latency_s"),
            "items": items,
        }
        texts.append(_flatten(payload))

    # 三段论完整性：反驳手的四段是否都填了（领域中立，法律包下即法律涵摄）
    syll_total = syll_complete = 0
    rebutter = latest.get("rebutter", {}).get("payload")
    if isinstance(rebutter, list):
        for item in rebutter:
            if not isinstance(item, dict):
                continue
            syll_total += 1
            if all(str(item.get(f, "")).strip() for f in REBUTTAL_FIELDS):
                syll_complete += 1

    # 引用核验（走本地语料，0 消耗）
    retriever = get_retriever()
    cites = verify_text("\n".join(texts), retriever)

    latencies = [
        float(v["latency_s"]) for v in advisor_stats.values()
        if isinstance(v.get("latency_s"), (int, float)) and v["status"] == "ok"
    ]

    case = _case_by_topic(snap["session"]["topic"])
    coverage = _focus_coverage("\n".join(texts), (case or {}).get("focus") or [])

    return {
        "session_id": session_id,
        "case_id": (case or {}).get("id"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "topic": snap["session"]["topic"],
        "our_side": snap["session"]["our_side"],
        "advisors": advisor_stats,
        "health": health,
        "structure": {
            "rebuttal_items": syll_total,
            "syllogism_complete": syll_complete,
            "syllogism_rate": round(syll_complete / syll_total, 3) if syll_total else None,
        },
        "focus": coverage,
        "citations": {
            "total": cites.total,
            "verified": cites.verified,
            "dubious": cites.dubious,
            "unverified": cites.unverified,
            "retriever": cites.retriever,
            "verify_rate": round(cites.verified / cites.total, 3) if cites.total else None,
        },
        "latency": {
            "n": len(latencies),
            "p50": _pct(latencies, 50),
            "p95": _pct(latencies, 95),
            "max": round(max(latencies), 2) if latencies else None,
        },
    }


def _pct(xs: list[float], p: float) -> Optional[float]:
    if not xs:
        return None
    xs = sorted(xs)
    idx = max(0, min(len(xs) - 1, int(round((p / 100) * (len(xs) - 1)))))
    return round(xs[idx], 2)


def evaluate_many(session_ids: list[str]) -> dict:
    """批量评估 + 汇总（回归对比用）。"""
    rows = [evaluate(sid) for sid in session_ids]
    rows = [r for r in rows if "error" not in r]

    def _avg(vals: list[float]) -> Optional[float]:
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    summary = {
        "sessions": len(rows),
        "cases_matched": sum(1 for r in rows if r.get("case_id")),
        "syllogism_rate": _avg([r["structure"]["syllogism_rate"] for r in rows]),
        "focus_rate": _avg([r["focus"]["rate"] for r in rows]),
        "cite_verify_rate": _avg([r["citations"]["verify_rate"] for r in rows]),
        "p50": _avg([r["latency"]["p50"] for r in rows]),
        "p95": _avg([r["latency"]["p95"] for r in rows]),
        "timeouts": sum(r["health"].get("timeout", 0) for r in rows),
        "errors": sum(r["health"].get("error", 0) for r in rows),
    }
    return {"summary": summary, "rows": rows}


# --------------------------------------------------------------------------
# 对比（回答"是变好了还是只是变长了"）
# --------------------------------------------------------------------------
def compare(before: dict, after: dict) -> list[str]:
    """给出两次评估的指标差异，明确标注变好/变差/基本不变。"""
    lines: list[str] = []
    pairs = [
        ("三段论完整率", before["structure"]["syllogism_rate"], after["structure"]["syllogism_rate"], True),
        ("要点覆盖率", before["focus"]["rate"], after["focus"]["rate"], True),
        ("引用核验率", before["citations"]["verify_rate"], after["citations"]["verify_rate"], True),
        ("P50 延迟(s)", before["latency"]["p50"], after["latency"]["p50"], False),
        ("P95 延迟(s)", before["latency"]["p95"], after["latency"]["p95"], False),
    ]
    for label, b, a, higher_better in pairs:
        if b is None or a is None:
            lines.append(f"- {label}：数据不足（{b} → {a}）")
            continue
        delta = a - b
        if abs(delta) < 1e-9:
            verdict = "不变"
        elif (delta > 0) == higher_better:
            verdict = "变好"
        else:
            verdict = "变差"
        lines.append(f"- {label}：{b} → {a}（{delta:+.3f}，{verdict}）")
    return lines


# --------------------------------------------------------------------------
# 真的跑模型（要花钱，必须显式确认）
# --------------------------------------------------------------------------
def estimate_live_calls(cases: list[dict]) -> int:
    """预计调用量＝每用例 × 启用的参谋路数。"""
    try:
        from app.advisors import load_roster

        per_case = len(load_roster())
    except Exception:  # noqa: BLE001
        per_case = 0
    return per_case * len(cases)


def run_live(cases: list[dict], base_url: str = "http://127.0.0.1:8010",
             budget_s: float = 30) -> list[str]:
    """真跑。**会产生 API 消耗**，调用方必须先确认。"""
    import httpx

    session_ids: list[str] = []
    with httpx.Client(timeout=180) as client:
        for case in cases:
            resp = client.post(f"{base_url}/api/analyze", json={
                "topic": case["topic"],
                "our_side": case["our_side"],
                "opponent_text": case["opponent_text"],
                "budget_s": budget_s,
            })
            resp.raise_for_status()
            sid = resp.json()["session_id"]
            session_ids.append(sid)
            print(f"  {case['id']}: session={sid} "
                  f"({resp.json()['total_latency_s']}s)")
    return session_ids


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _save(obj: Any, name: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "help"

    if cmd == "list":
        cases = load_cases()
        print(f"用例目录：{CASES_DIR}")
        for c in cases:
            print(f"  {c['id']:24s} {c['topic']}")
        print(f"共 {len(cases)} 例")
        return 0

    if cmd == "check":
        errors = validate_cases()
        if errors:
            print("用例校验未通过：")
            for e in errors:
                print("  -", e)
            return 1
        print(f"用例校验通过（{len(load_cases())} 例）。本命令不消耗 API。")
        return 0

    if cmd == "eval":
        if len(argv) < 2:
            print("用法：python -m benchmarks.runner eval <session_id> [session_id...]")
            return 2
        result = evaluate_many(argv[1:])
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        path = _save(result, f"eval-{datetime.now():%Y%m%d-%H%M%S}.json")
        print(f"结果已写入 {path.relative_to(ROOT)}（本命令不消耗 API）")
        return 0

    if cmd == "compare":
        if len(argv) < 3:
            print("用法：python -m benchmarks.runner compare <before.json> <after.json>")
            return 2
        before = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        after = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        # 支持传入 evaluate_many 的整体结果或单次评估结果
        b = before["rows"][0] if "rows" in before else before
        a = after["rows"][0] if "rows" in after else after
        print("指标差异（本命令不消耗 API）：")
        for line in compare(b, a):
            print(" ", line)
        return 0

    if cmd == "run":
        if "--live" not in argv:
            print("本命令会**真实调用模型并产生费用**。")
            print("确认要跑，请加 --live：")
            print("  python -m benchmarks.runner run --live --confirm")
            print(f"（当前用例数 {len(load_cases())}，"
                  f"预计调用 {estimate_live_calls(load_cases())} 次）")
            return 2
        if "--confirm" not in argv:
            print(f"预计产生 {estimate_live_calls(load_cases())} 次上游调用。")
            print("再加 --confirm 才会真正执行。")
            return 2
        cases = load_cases()
        print(f"开始跑 {len(cases)} 例（预计 {estimate_live_calls(cases)} 次调用）……")
        sids = run_live(cases)
        result = evaluate_many(sids)
        path = _save(result, f"live-{datetime.now():%Y%m%d-%H%M%S}.json")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        print(f"结果已写入 {path.relative_to(ROOT)}")
        return 0

    print(__doc__)
    print("命令：list | check | eval <sid...> | compare <a.json> <b.json> | run --live --confirm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
