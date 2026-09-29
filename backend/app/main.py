"""FastAPI 入口：参谋分析与 SSE 推送。

端点：
  GET  /api/health           健康检查（含上游是否配置、参谋名册）
  POST /api/analyze          一次性返回全部参谋结果
  GET  /api/analyze/stream   SSE：每完成一路推一路（现场模式用）
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import config, consistency, mavis_bridge
from .advisors import DebateContext, load_roster
from .ledger import store
from .orchestrator import run_advisors
from .schemas import AnalyzeResponse

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("api")

app = FastAPI(title="法学辩论现场参谋台", version="0.2.0")

# 前端 dev server 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    topic: str
    our_side: str = "控方（主张应享有）"
    opponent_text: str
    session_id: str | None = None
    retry: int = 2


class SessionRequest(BaseModel):
    topic: str
    our_side: str = "控方（主张应享有）"
    session_id: str | None = None


class CardRequest(BaseModel):
    claim: str
    major_premise: str = ""
    minor_premise: str = ""
    conclusion: str = ""
    source: str = "manual"


class CardPatch(BaseModel):
    status: str


class ConsistencyRequest(BaseModel):
    claims: list[str]


def _prepare(
    session_id: str | None, topic: str, our_side: str, opponent_text: str
) -> tuple[DebateContext, str]:
    """建/取会话 → 记录本次对方发言 → 把台账里的"我方已主张"注入上下文。

    注入台账是**防止立场漂移的第一道闸**：参谋在生成建议时就知道
    我方此前主张过什么，不会给出与己方立场冲突的建议。
    """
    session = store.get_or_create_session(
        session_id, topic.strip(), our_side.strip()
    )
    sid = session["id"]
    store.add_turn(sid, opponent_text.strip())
    ctx = DebateContext(
        topic=topic.strip(),
        our_side=our_side.strip(),
        opponent_text=opponent_text.strip(),
        our_ledger=store.standing_claims(sid),
    )
    return ctx, sid


@app.get("/api/health")
async def health():
    roster = load_roster()
    return {
        "ok": True,
        "model": config.LLM_MODEL,
        "bridge": config.LLM_BRIDGE_URL,
        "upstream_configured": config.upstream_configured(),
        "advisors": [{"name": a.name, "label": a.label} for a in roster],
    }


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    ctx, sid = _prepare(req.session_id, req.topic, req.our_side, req.opponent_text)
    roster = load_roster()
    # 同步阻塞调用放到线程池，避免堵住事件循环
    results, total = await asyncio.to_thread(run_advisors, ctx, roster, None, req.retry)
    await asyncio.to_thread(store.save_suggestions, sid, results)
    return AnalyzeResponse(
        session_id=sid, topic=ctx.topic, our_side=ctx.our_side,
        opponent_text=ctx.opponent_text, total_latency_s=total, results=results,
        our_ledger=ctx.our_ledger,
    )


@app.get("/api/analyze/stream")
async def analyze_stream(
    topic: str = Query(...),
    opponent_text: str = Query(...),
    our_side: str = Query("控方（主张应享有）"),
    session_id: str | None = Query(None),
    retry: int = Query(2),
):
    """SSE：先推会话信息，再每完成一路参谋推一条，最后推 done。

    用 GET 是因为浏览器 EventSource 不支持 POST；输入走 query。
    """
    ctx, sid = _prepare(session_id, topic, our_side, opponent_text)
    roster = load_roster()
    out_queue: queue.Queue = queue.Queue()

    def worker():
        started = time.time()
        collected = []
        try:
            results, _ = run_advisors(
                ctx, roster,
                on_result=lambda r: (collected.append(r), out_queue.put(r)),
                retry=retry,
            )
            store.save_suggestions(sid, results)
        except Exception as exc:  # noqa: BLE001
            logger.exception("SSE worker 异常")
            out_queue.put({"advisor": "_error", "label": "系统", "status": "error",
                           "latency_s": 0.0, "error": repr(exc), "kind": "text"})
        out_queue.put({
            "advisor": "_done", "label": "", "status": "ok", "session_id": sid,
            "our_ledger": ctx.our_ledger,
            "latency_s": round(time.time() - started, 2), "kind": "meta",
        })

    threading.Thread(target=worker, daemon=True).start()

    async def event_gen():
        yield ": connected\n\n"
        yield (
            "event: session\ndata: "
            + json.dumps(
                {"session_id": sid, "our_ledger": ctx.our_ledger,
                 "advisors": [a.name for a in roster]},
                ensure_ascii=False,
            )
            + "\n\n"
        )
        while True:
            item = await asyncio.to_thread(out_queue.get)
            if isinstance(item, dict) and item.get("advisor") == "_done":
                yield f"event: done\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                break
            if isinstance(item, dict) and item.get("advisor") == "_error":
                yield f"event: error\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                continue
            payload = item.model_dump() if hasattr(item, "model_dump") else item
            yield f"event: advisor\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------
# 会话与论点台账
# --------------------------------------------------------------------------
@app.post("/api/session")
async def create_or_get_session(req: SessionRequest):
    session = store.get_or_create_session(req.session_id, req.topic, req.our_side)
    return {"session": session, "cards": store.list_cards(session["id"])}


@app.get("/api/sessions")
async def list_sessions(limit: int = Query(20)):
    return {"sessions": store.list_sessions(limit)}


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    snap = store.snapshot(session_id)
    if not snap:
        return {"error": "session not found"}
    return snap


@app.post("/api/session/{session_id}/cards")
async def add_card(session_id: str, req: CardRequest):
    if not store.get_session(session_id):
        return {"error": "session not found"}
    card = store.add_card(
        session_id, req.claim.strip(), req.major_premise.strip(),
        req.minor_premise.strip(), req.conclusion.strip(), req.source,
    )
    return {"card": card, "cards": store.list_cards(session_id)}


@app.patch("/api/cards/{card_id}")
async def patch_card(card_id: str, req: CardPatch):
    try:
        ok = store.update_card(card_id, req.status)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": ok, "card_id": card_id, "status": req.status}


@app.delete("/api/cards/{card_id}")
async def remove_card(card_id: str):
    return {"ok": store.delete_card(card_id)}


@app.post("/api/session/{session_id}/check-consistency")
async def check_consistency(session_id: str, req: ConsistencyRequest):
    """把新生成的建议与我方台账比对，找出立场冲突（阶段 3 的第二道闸）。"""
    conflicts = await asyncio.to_thread(consistency.check, session_id, req.claims)
    return {"conflicts": conflicts, "checked_claims": len(req.claims)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level="info")
