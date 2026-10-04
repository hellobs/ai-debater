"""论点台账（SQLite）。

为什么台账必须外置
------------------
mavis 的记忆是**非结构化情景记忆**（三因子检索），metadata 是固定 schema，
塞额外字段会直接 `TypeError`——结构化论点卡片进不去。
所以台账放在我们自己这边，这也符合本来就必须"业务逻辑在 mavis 之外"的约束。
（见 docs/spike-0-report.md）

台账的作用：把"我方已经主张过什么"钉住，避免参谋在后续轮次给出与己方
此前立场冲突的建议（即"立场漂移"）。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .. import config
from ..schemas import jsonable

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id          TEXT PRIMARY KEY,
  topic       TEXT NOT NULL,
  our_side    TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id    TEXT NOT NULL,
  opponent_text TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
  id               TEXT PRIMARY KEY,
  session_id       TEXT NOT NULL,
  claim            TEXT NOT NULL,
  major_premise    TEXT DEFAULT '',
  minor_premise    TEXT DEFAULT '',
  conclusion       TEXT DEFAULT '',
  source           TEXT DEFAULT 'manual',
  status           TEXT DEFAULT 'standing',
  challenged_count INTEGER DEFAULT 0,
  created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL,
  advisor     TEXT NOT NULL,
  status      TEXT,
  latency_s   REAL,
  payload     TEXT,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  advisor    TEXT NOT NULL,
  rating     INTEGER,
  selected   INTEGER DEFAULT 0,
  note       TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(session_id, advisor)
);

CREATE TABLE IF NOT EXISTS citation_reports (
  session_id  TEXT PRIMARY KEY,
  report_json TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cards_session ON cards(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_sugg_session  ON suggestions(session_id);
"""

VALID_STATUS = ("standing", "weakened", "abandoned")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    path = Path(config.LEDGER_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(SCHEMA)


# --------------------------------------------------------------------------
# 会话
# --------------------------------------------------------------------------
def create_session(topic: str, our_side: str) -> dict:
    init_db()
    sid = uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, topic, our_side, created_at) VALUES (?,?,?,?)",
            (sid, topic, our_side, _now()),
        )
    return {"id": sid, "topic": topic, "our_side": our_side}


def get_or_create_session(session_id: Optional[str], topic: str, our_side: str) -> dict:
    if session_id:
        s = get_session(session_id)
        if s:
            return s
    return create_session(topic, our_side)


def get_session(session_id: str) -> Optional[dict]:
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_sessions(limit: int = 20) -> list[dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]

#: 挂在 sessions 下的关联表 —— 删会话时一并清掉，否则台账里会剩下孤儿行。
_SESSION_CHILDREN = ("turns", "cards", "suggestions", "feedback", "citation_reports")


def delete_session(session_id: str) -> bool:
    """删掉一条会话及其全部关联数据。

    为什么需要：台账**只会增** —— 原先没有任何删会话的入口（后端没路由、界面里也没有），
    你打过的对话（辩题、对方发言原文、采纳的参谋、反馈评分、引用核验记录）会一直躺在
    SQLite 里。用户必须能主动删掉自己的咨询记录。

    删在同一个事务里：要么全没，要么全没，不留半删状态。
    """
    init_db()
    with _conn() as conn:
        # 表名不能参数化，只能写成字面量（本模块内的白名单，不含用户输入）
        for table in _SESSION_CHILDREN:
            conn.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
        cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        return cur.rowcount > 0


# --------------------------------------------------------------------------
# 对方发言
# --------------------------------------------------------------------------
def add_turn(session_id: str, opponent_text: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO turns (session_id, opponent_text, created_at) VALUES (?,?,?)",
            (session_id, opponent_text, _now()),
        )
        return int(cur.lastrowid)


def list_turns(session_id: str) -> list[dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM turns WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# 论点卡片
# --------------------------------------------------------------------------
def add_card(
    session_id: str,
    claim: str,
    major_premise: str = "",
    minor_premise: str = "",
    conclusion: str = "",
    source: str = "manual",
) -> dict:
    init_db()
    cid = uuid.uuid4().hex[:8]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO cards (id, session_id, claim, major_premise, minor_premise,"
            " conclusion, source, status, created_at) VALUES (?,?,?,?,?,?,?,'standing',?)",
            (cid, session_id, claim, major_premise, minor_premise, conclusion, source, _now()),
        )
    return {"id": cid}


def list_cards(session_id: str, status: Optional[str] = None) -> list[dict]:
    init_db()
    sql = "SELECT * FROM cards WHERE session_id=?"
    args: list[Any] = [session_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY created_at, id"
    with _conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def update_card(card_id: str, status: Optional[str] = None) -> bool:
    if status is not None and status not in VALID_STATUS:
        raise ValueError(f"status 必须是 {VALID_STATUS} 之一")
    init_db()
    with _conn() as conn:
        cur = conn.execute("UPDATE cards SET status=? WHERE id=?", (status, card_id))
        return cur.rowcount > 0


def delete_card(card_id: str) -> bool:
    init_db()
    with _conn() as conn:
        cur = conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
        return cur.rowcount > 0


def list_all_cards() -> list[dict]:
    """全库卡片（偏好对导出用：跨会话找"采纳 vs 原文"对）。"""
    init_db()
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM cards ORDER BY created_at, id").fetchall()
    return [dict(r) for r in rows]


def standing_claims(session_id: str) -> list[str]:
    """注入提示词用的"我方已主张"清单（只取仍站得住的）。"""
    return [c["claim"] for c in list_cards(session_id, status="standing")]


# --------------------------------------------------------------------------
# 参谋建议存档
# --------------------------------------------------------------------------
def save_suggestions(session_id: str, results: list[Any]) -> None:
    init_db()
    rows = []
    for r in results:
        payload = r.payload if hasattr(r, "payload") else None
        rows.append((
            session_id,
            getattr(r, "advisor", "?"),
            getattr(r, "status", None),
            getattr(r, "latency_s", None),
            json.dumps(jsonable(payload), ensure_ascii=False, default=str),
            _now(),
        ))
    with _conn() as conn:
        conn.executemany(
            "INSERT INTO suggestions (session_id, advisor, status, latency_s, payload,"
            " created_at) VALUES (?,?,?,?,?,?)",
            rows,
        )


def save_suggestion(session_id: str, result: Any) -> None:
    """逐条保存：参谋**一完成就落库**。

    这样即使 SSE 连接中断，前端也能通过快照把已经算好的那几路恢复出来，
    不必重新花 token 再跑一遍。
    """
    init_db()
    payload = getattr(result, "payload", None)
    with _conn() as conn:
        conn.execute(
            "INSERT INTO suggestions (session_id, advisor, status, latency_s, payload,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (
                session_id,
                getattr(result, "advisor", "?"),
                getattr(result, "status", None),
                getattr(result, "latency_s", None),
                json.dumps(jsonable(payload), ensure_ascii=False, default=str),
                _now(),
            ),
        )


def list_suggestions(session_id: str) -> list[dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM suggestions WHERE session_id=? ORDER BY id DESC LIMIT 50",
            (session_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"] or "null")
        except Exception:  # noqa: BLE001
            pass
        out.append(d)
    return out


def _percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    xs = sorted(values)
    idx = max(0, min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1)))))
    return round(xs[idx], 2)


def latency_stats() -> dict:
    """各路参谋的延迟与成功率统计（现场模式的仪表）。"""
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT advisor, latency_s, status FROM suggestions"
        ).fetchall()

    buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        b = buckets.setdefault(
            r["advisor"],
            {"latencies": [], "ok": 0, "timeout": 0, "error": 0, "empty": 0, "total": 0},
        )
        b["total"] += 1
        status = r["status"]
        if status == "ok":
            b["ok"] += 1
            if r["latency_s"] is not None:
                b["latencies"].append(float(r["latency_s"]))
        elif status == "timeout":
            b["timeout"] += 1
        elif status == "error":
            b["error"] += 1
        else:
            b["empty"] += 1

    out: dict[str, dict[str, Any]] = {}
    for name, b in buckets.items():
        lat = b["latencies"]
        out[name] = {
            "total": b["total"],
            "ok": b["ok"],
            "timeout": b["timeout"],
            "error": b["error"],
            "empty": b["empty"],
            "p50": _percentile(lat, 50),
            "p95": _percentile(lat, 95),
            "max": round(max(lat), 2) if lat else None,
            "ok_rate": round(b["ok"] / b["total"], 3) if b["total"] else None,
        }
    return out


# --------------------------------------------------------------------------
# 反馈（评分 / 收录为训练样本）—— 闭环数据的源头
# --------------------------------------------------------------------------
def save_feedback(session_id: str, advisor: str, rating: Optional[int],
                  selected: bool, note: str = "") -> dict:
    """按 (session_id, advisor) upsert：界面上评的是"这一路在本会话的最新回答"。"""
    init_db()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO feedback (session_id, advisor, rating, selected, note, created_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(session_id, advisor) DO UPDATE SET"
            " rating=excluded.rating, selected=excluded.selected,"
            " note=excluded.note, created_at=excluded.created_at",
            (session_id, advisor, rating, 1 if selected else 0, note, _now()),
        )
    return {"session_id": session_id, "advisor": advisor,
            "rating": rating, "selected": selected, "note": note}


def list_feedback(session_id: Optional[str] = None) -> list[dict]:
    init_db()
    with _conn() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM feedback WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM feedback ORDER BY id").fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# 引用核验报告持久化 —— "证据随消息落库"：报告与会话绑定，刷新/复盘可回溯
# --------------------------------------------------------------------------
def save_citation_report(session_id: str, report: dict) -> None:
    """按会话 upsert 最新一份核验报告（同一会话只留最新——报告本身是全量的）。"""
    init_db()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO citation_reports (session_id, report_json, created_at)"
            " VALUES (?,?,?)"
            " ON CONFLICT(session_id) DO UPDATE SET"
            " report_json=excluded.report_json, created_at=excluded.created_at",
            (session_id, json.dumps(report, ensure_ascii=False), _now()),
        )


def get_citation_report(session_id: str) -> Optional[dict]:
    init_db()
    with _conn() as conn:
        row = conn.execute(
            "SELECT report_json FROM citation_reports WHERE session_id=?", (session_id,)
        ).fetchone()
    return json.loads(row["report_json"]) if row else None


def snapshot(session_id: str) -> Optional[dict]:
    session = get_session(session_id)
    if not session:
        return None
    return {
        "session": session,
        "turns": list_turns(session_id),
        "cards": list_cards(session_id),
        "suggestions": list_suggestions(session_id),
    }
