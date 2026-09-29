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

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import config, mavis_bridge
from .advisors import DebateContext, load_roster
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
    retry: int = 2


def _ctx(req) -> DebateContext:
    return DebateContext(
        topic=req.topic.strip(),
        our_side=req.our_side.strip(),
        opponent_text=req.opponent_text.strip(),
    )


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
    ctx = _ctx(req)
    roster = load_roster()
    # 同步阻塞调用放到线程池，避免堵住事件循环
    results, total = await asyncio.to_thread(run_advisors, ctx, roster, None, req.retry)
    return AnalyzeResponse(
        topic=ctx.topic, our_side=ctx.our_side, opponent_text=ctx.opponent_text,
        total_latency_s=total, results=results,
    )


@app.get("/api/analyze/stream")
async def analyze_stream(
    topic: str = Query(...),
    opponent_text: str = Query(...),
    our_side: str = Query("控方（主张应享有）"),
    retry: int = Query(2),
):
    """SSE：每完成一路参谋推一条，最后推 done。

    用 GET 是因为浏览器 EventSource 不支持 POST；输入走 query。
    """
    ctx = DebateContext(
        topic=topic.strip(),
        our_side=our_side.strip(),
        opponent_text=opponent_text.strip(),
    )
    roster = load_roster()
    out_queue: queue.Queue = queue.Queue()

    def worker():
        started = __import__("time").time()
        try:
            run_advisors(ctx, roster, on_result=out_queue.put, retry=retry)
        except Exception as exc:  # noqa: BLE001
            logger.exception("SSE worker 异常")
            out_queue.put({"advisor": "_error", "label": "系统", "status": "error",
                           "latency_s": 0.0, "error": repr(exc), "kind": "text"})
        out_queue.put({
            "advisor": "_done", "label": "", "status": "ok",
            "latency_s": round(__import__("time").time() - started, 2), "kind": "meta",
        })

    threading.Thread(target=worker, daemon=True).start()

    async def event_gen():
        yield ": connected\n\n"
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level="info")
