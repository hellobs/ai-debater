"""FastAPI 入口：参谋分析与 SSE 推送。

端点：
  GET  /api/health           健康检查（含上游状态、参谋名册元数据）
  GET  /api/analyze/stream   SSE（GET 旧形态，脚本兼容；长文本受 URL 上限约束）
  POST /api/analyze/stream   SSE（前端在用；输入走 JSON body）
  POST /api/analyze          一次性返回全部参谋结果
  GET  /api/upstream         当前上游（脱敏）+ 可选形态
  POST /api/upstream         切换上游 / 换模型（只改内存）
  GET  /api/models           探测可用模型（不产生推理调用）
  GET  /api/topics           辩题库（预设 + 本机）
  POST /api/topics           存一条本机辩题
  DELETE /api/topics/{id}    删一条本机辩题
  POST /api/corpus/import    导入法条全文进语料库（纯本地，0 消耗；核验立刻生效）
  POST /api/asr/transcribe   语音转文字（纯本地，0 消耗；结果只填输入框）
  WS   /api/asr/stream       流式转写（纯本地，0 消耗；边说边出字，端点自动分段）
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import (
    asr as asr_mod,
    config,
    consistency,
    corpus as corpus_mod,
    mavis_bridge,
    observers,
    prompt_packs,
    retrieval as retrieval_mod,
    topics as topics_mod,
)
from .advisors import DebateContext, load_roster
from .asr.base import pcm16_to_float32
from .export import report as report_mod
from .ledger import store
from .orchestrator import run_advisors
from .retrieval.statute_text import StatuteParseError
from .schemas import AnalyzeResponse
from . import llm_bridge, upstream

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("api")

#: 服务版本。**这里是唯一来源**：OpenAPI 文档、`/api/health` 的 `version`、
#: 界面「服务状态」都读它，不用在别处再抄一份。发版时改这一处（另一处是
#: frontend/package.json —— npm 不认识 Python 的常量，见 CONTRIBUTING §7）。
VERSION = "1.3.1"

app = FastAPI(title=config.BRAND_NAME, version=VERSION)

# 协议桥 mount 在本进程上（/bridge/v1/...）。
#
# 原先它是独立进程（8011），于是"换模型/换网关"必须重启两个进程，界面上
# 做不出一个下拉框。mount 进来之后，上游只是本进程内存里的一个配置对象
# （见 app/upstream.py），改完立刻生效。
# 独立跑法仍然支持：`python -m app.llm_bridge` 还是那个 8011 的桥，行为不变。
app.mount("/bridge", llm_bridge.app)

# 前端 dev server 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

#: 跨站请求伪造（CSRF）防护头。**浏览器无法在跨站简单请求（GET /
#: text/plain POST）里携带自定义头**——自定义头会强制 CORS 预检并被浏览器
#: 拦截。因此「请求带了这个头」≈「请求来自本界面」，而恶意网页发不出它。
UI_GUARD_HEADER = "X-Debater-UI"
UI_GUARD_VALUE = "1"

#: 免检前缀：协议桥的调用方是 mavis（服务端进程），不是浏览器，
#: 要求 UI 头会直接打断模型调用。桥的攻击面由"只监听本机 + 凭据不落盘"承担。
_EXEMPT_PREFIXES = ("/bridge",)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """计费与写盘端点必须携带 UI_GUARD_HEADER（防跨站触发计费/污染语料）。

    规则刻意收紧到**一切非 GET** 加上**计费的旧 GET**：
    - GET 读接口（health / topics / 导出等）不涉钱不落盘，放行——
      恶意网页也读不到跨源响应（无 CORS 许可）。
    - `GET /api/analyze/stream` 是保留给脚本的旧形态，但它**触发 5 次真实
      计费**，与其他计费端点同规则。
    - WebSocket 无法自定义请求头（浏览器限制），`/api/asr/stream` 由端点内
      的 Origin 校验单独防护（见 asr_stream）；且它纯本地计算，风险本身低。
    """
    path = request.url.path
    if not any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        is_mutating = request.method != "GET" or path == "/api/analyze/stream"
        if is_mutating and request.headers.get(UI_GUARD_HEADER) != UI_GUARD_VALUE:
            return JSONResponse(
                {"detail": f"缺少 {UI_GUARD_HEADER}: {UI_GUARD_VALUE} 头——"
                           "计费与写盘端点只接受本界面发起的请求"},
                status_code=403,
            )
    return await call_next(request)

#: 立场缺省值。具体立场应由辩题带出（见 /api/topics），这里只是兜底。
DEFAULT_SIDE = "正方"


class AnalyzeRequest(BaseModel):
    topic: str
    our_side: str = DEFAULT_SIDE
    opponent_text: str
    #: 辩题领域（辩题库里那条 domain）。**它决定提示词用哪个包**：
    #: 「AI + 法学」走 legal 包，其余走默认的 general 包。留空 = 自由输入。
    domain: str = ""
    session_id: str | None = None
    retry: int = 2
    budget_s: float | None = None


class SessionRequest(BaseModel):
    topic: str
    our_side: str = DEFAULT_SIDE
    session_id: str | None = None


class TopicRequest(BaseModel):
    """存一条本机辩题。id 留空则按标题自动生成（同标题覆盖）。"""

    title: str
    id: str | None = None
    domain: str = ""
    side_a: str = ""
    side_b: str = ""
    opponent_hint: str = ""
    note: str = ""


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


class VerifyRequest(BaseModel):
    texts: list[str] | None = None      # 不传则核验会话里最新一轮的参谋产出


def _flatten(obj) -> str:
    """把任意嵌套的参谋产出摊平成纯文本，供引用抽取使用。"""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return "\n".join(_flatten(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return "\n".join(_flatten(v) for v in obj)
    return str(obj)


def _prepare(
    session_id: str | None,
    topic: str,
    our_side: str,
    opponent_text: str,
    domain: str = "",
) -> tuple[DebateContext, str]:
    """建/取会话 → 记录本次对方发言 → 把台账里的"我方已主张"注入上下文。

    注入台账是**防止立场漂移的第一道闸**：参谋在生成建议时就知道
    我方此前主张过什么，不会给出与己方立场冲突的建议。

    `domain` 只影响提示词用哪个包（legal / general），不影响任何落库字段
    —— 会话表里没有 domain，所以**复盘时无法回溯当轮用了哪个包**，
    这件事记在 HANDOVER 的待办里，不算已解决。
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
        domain=domain.strip(),
    )
    return ctx, sid


class UpstreamRequest(BaseModel):
    """改上游。每个字段都可省略；`api_key=None` 表示**不动**（不是清空）。"""

    kind: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


# --------------------------------------------------------------------------
# 上游与模型（运行时可改；凭据只驻留内存）
# --------------------------------------------------------------------------
@app.get("/api/upstream")
async def get_upstream():
    """当前生效的上游（脱敏）+ 可选形态。不产生任何上游调用。"""
    return {
        "ok": True,
        "upstream": upstream.current().public(),
        "kinds": list(upstream.KINDS),
    }


@app.post("/api/upstream")
async def set_upstream(req: UpstreamRequest):
    """切换上游 / 换模型。

    只改内存：`anthropic` 形态下把地址与凭据交给进程内的桥，其余形态 mavis 直连。
    改完必须 `reset_provider()` —— mavis 的 provider 构造时就把地址定死了。
    """
    try:
        settings = upstream.update(
            kind=req.kind, base_url=req.base_url, model=req.model, api_key=req.api_key
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if settings.kind == "anthropic":
        llm_bridge.CFG.base = settings.base_url
        llm_bridge.CFG.token = settings.api_key
    mavis_bridge.reset_provider()
    return {"ok": True, "upstream": settings.public()}


@app.get("/api/models")
async def list_models(
    kind: str | None = Query(None),
    base_url: str | None = Query(None),
):
    """探测可用模型。**不产生推理调用，不计费**。

    凭据只从内存里已保存的那份取（不从 URL 传 —— 明文密钥不该进查询串、
    进日志、进浏览器历史）。所以界面的顺序是：先保存上游，再刷模型列表。
    探测不到时如实报错，由界面退回手填 —— 不拿写死的清单冒充"可用模型"。
    """
    models, err, probed = upstream.probe_models(kind=kind, base_url=base_url)
    return {
        "ok": not err,
        "models": models,
        "error": err,
        # 这份清单属于哪份配置：界面据此判断"改了形态/地址后要不要重探"
        "kind": probed["kind"],
        "base_url": probed["base_url"],
    }


@app.get("/api/health")
async def health():
    roster = load_roster()
    # mavis 的接入自述：版本 / 只读标记 / 唯一接触面 / 用满的三面 / 模板清单。
    # 与 README、导出报告同源，避免"文档一套、代码一套"。
    mavis = mavis_bridge.runtime_info()
    mavis["observers"] = list(observers.OBSERVER_NAMES)
    return {
        "ok": True,
        "brand": config.BRAND_NAME,
        # 服务版本（唯一来源是上面的 VERSION 常量，界面「服务状态」直接读这里）
        "version": app.version,
        "model": upstream.current().model or config.LLM_MODEL,
        "bridge": upstream.current().mavis_base_url(),
        "upstream_configured": config.upstream_configured(),
        "budget_s": config.ADVISOR_BUDGET_S,
        # 当前生效的上游（脱敏：凭据只报有没有）。界面据此渲染「模型与上游」，
        # 不再把模型名写死在前端。
        "upstream": upstream.current().public(),
        # 完整元数据（含 kind / domain）：前端据此渲染参谋列，
        # 不再自己抄一份名册。kind 决定用哪种卡片，domain 决定是否标注场景专用。
        "advisors": [a.meta() for a in roster],
        # 语音转写（阶段 7 一期）的就绪状态：界面据此禁用/启用收音按钮，
        # 并把「为什么不可用」直接说给用户听（如模型未下载），不做静默降级。
        "asr": asr_mod.status(),
        # 本项目的底座是 mavis：版本、用满的三面、唯一接触面都在这
        "mavis": mavis,
        # mavis provider 的快照：逐 caller 的 成功/失败/重试 计数 + 缓存统计。
        # 不产生上游调用（只是读 provider 自己维护的计数器）。
        "provider": mavis_bridge.provider_info(),
        # 本进程的实时观察数据（跨会话的历史分布看 /api/metrics）
        "observers": observers.PROCESS_METRICS.report(),
    }


# --------------------------------------------------------------------------
# 辩题库（纯本地文件读写，零 API 消耗）
# --------------------------------------------------------------------------
def _topics_payload() -> dict:
    topics = topics_mod.load_topics()
    return {"topics": [t.to_dict() for t in topics], "count": len(topics)}


@app.get("/api/topics")
async def list_topics():
    """预设（configs/topics.yaml）+ 本机（data/topics.json）的并集。"""
    return _topics_payload()


@app.post("/api/topics")
async def create_topic(req: TopicRequest):
    """保存一条本机辩题。同 id（或同标题）覆盖，不会堆重复。"""
    try:
        topics_mod.save_local_topic(
            req.title, topic_id=req.id, domain=req.domain,
            side_a=req.side_a, side_b=req.side_b,
            opponent_hint=req.opponent_hint, note=req.note,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return _topics_payload()


@app.delete("/api/topics/{topic_id}")
async def remove_topic(topic_id: str):
    """删除一条**本机**辩题。入仓预设删不掉（ok=false）。"""
    ok = topics_mod.delete_local_topic(topic_id)
    return {"ok": ok, **_topics_payload()}


# --------------------------------------------------------------------------
# 语料导入（阶段 4 补充）：界面导入法条全文，让引用核验能判「已核验」。
# 纯本地文件操作与文本解析，**不调用任何 LLM**，0 API 消耗。
# --------------------------------------------------------------------------
class CorpusImportRequest(BaseModel):
    """导入一段法条全文。`law` 留空则从正文首行识别（《XX法》）。"""

    law: str = ""
    text: str


@app.post("/api/corpus/import")
async def import_corpus(req: CorpusImportRequest):
    """结构化一段法条全文进语料库并热重载检索层。

    同名法整体替换，其他已导入的法不动。解析失败（切不出条款 / 认不出法名 /
    旧语料文件损坏）返回 `{"error": 原因}`——错误要说到人能照着修。
    """
    try:
        result = await asyncio.to_thread(corpus_mod.import_text, req.text, req.law)
    except (StatuteParseError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    # 热重载：LocalCorpusRetriever 构造时读文件，重建即生效，不必重启后端
    await asyncio.to_thread(retrieval_mod.get_retriever, True)
    return {"ok": True, **result}


# --------------------------------------------------------------------------
# 语音转写（阶段 7 一期：批式。纯本地推理，本组接口**不调用任何 LLM**，0 API 消耗）
# --------------------------------------------------------------------------
@app.post("/api/asr/transcribe")
async def asr_transcribe(request: Request):
    """把一段录音转成文字，填进前端「对方刚说的话」输入框。

    请求体是**裸 PCM**（16bit 小端、单声道），采样率放 `X-Sample-Rate` 头
    （ sherpa-onnx 遇到与模型不符的采样率会内部重采样）。不用 multipart
    是为了不给项目凭空加 python-multipart 依赖——音频就是一坨字节。

    转写结果**只填输入框，不自动触发分析**：识别错字由人校对后再提交，
    「以什么文本去问参谋」的决策权归使用者。引擎不可用时返回
    `{"ok": false, "error": 原因}`（200）——这不是请求方的错，犯不上 4xx/5xx，
    前端把原因亮出来即可。
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="请求体为空：需要一段 PCM 音频")
    try:
        sample_rate = int(request.headers.get("x-sample-rate") or 16000)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Sample-Rate 头不是整数")
    transcriber = asr_mod.get_transcriber()
    if not transcriber.available:
        return {"ok": False, "error": transcriber.unavailable_reason,
                "engine": transcriber.name}
    try:
        result = await asyncio.to_thread(
            transcriber.transcribe, body, sample_rate
        )
    except Exception as exc:  # noqa: BLE001 —— 转写失败要给得出原因，不能静默空文本
        logger.exception("ASR 转写失败")
        return {"ok": False, "error": f"转写失败：{exc}", "engine": transcriber.name}
    return {"ok": True, **result.to_dict()}


@app.websocket("/api/asr/stream")
async def asr_stream(ws: WebSocket):
    """流式转写（阶段 7 二期）：边说边出字。

    协议（JSON 控制帧 over WebSocket，二进制帧传音频）：

    - 客户端 → 服务端：先一帧 `{"type":"config","sample_rate":16000}`（可省略），
      随后每帧**裸 PCM**（16bit 小端、单声道，建议 ~100ms 一帧），
      结束发一帧 `{"type":"stop"}`。
    - 服务端 → 客户端：`{"type":"ready"}` 就绪；`{"type":"partial","text"}`
      当前段实时文本；`{"type":"segment","text"}` 端点检测切出的**已完成段**
      （说完停顿 ~2.4s 自动切）；`{"type":"final","text"}` 收到 stop 后的最后
      一段。全文 = 已收 segment 依次拼接 + final。
    - 模型未下载时回 `{"type":"error","reason"}` 后关闭——说到人能照着修。

    与批式（`/api/asr/transcribe`）的分工见 asr/streaming.py 模块说明：
    流式管延迟，批式管质量，二者并存、UI 默认流式。
    """
    from .asr import streaming

    # WebSocket 浏览器端无法自定义头，改用 Origin 校验：浏览器一定带 Origin，
    # 同源时 Origin 的 host 与 Host 头一致；跨站（恶意网页）二者必不一致。
    # 非浏览器客户端（本地脚本）可以不带 Origin，放行。
    origin = ws.headers.get("origin")
    if origin:
        from urllib.parse import urlparse

        if urlparse(origin).netloc and urlparse(origin).netloc != ws.headers.get("host"):
            await ws.close(code=1008)  # Policy Violation
            return

    await ws.accept()
    if not streaming.stream_available():
        await ws.send_json({"type": "error", "reason": streaming.unavailable_reason()})
        await ws.close()
        return

    try:
        recognizer = await asyncio.to_thread(streaming.get_recognizer)
    except Exception as exc:  # noqa: BLE001 —— 加载失败要给得出原因
        logger.exception("流式识别器加载失败")
        await ws.send_json({"type": "error", "reason": f"识别器加载失败：{exc}"})
        await ws.close()
        return

    await ws.send_json({"type": "ready"})
    stream = recognizer.create_stream()
    rate = 16000
    last_partial = ""
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            text = msg.get("text")
            audio = msg.get("bytes")
            if text is not None:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "reason": "控制帧不是合法 JSON"})
                    break
                if data.get("type") == "config":
                    rate = int(data.get("sample_rate") or 16000)
                    continue
                if data.get("type") == "stop":
                    stream.input_finished()
                    with streaming.decode_lock:
                        while recognizer.is_ready(stream):
                            recognizer.decode_stream(stream)
                        tail = recognizer.get_result(stream)
                    await ws.send_json({"type": "final", "text": tail})
                    return
                continue
            if audio:
                samples = pcm16_to_float32(audio)
                if not samples:
                    continue
                stream.accept_waveform(rate, samples)
                # 解码必须持锁：识别器跨连接共享（见 streaming.decode_lock）。
                # 单帧解码是毫秒级，串行化不影响实时性。
                with streaming.decode_lock:
                    while recognizer.is_ready(stream):
                        recognizer.decode_stream(stream)
                    partial = recognizer.get_result(stream)
                if partial and partial != last_partial:
                    last_partial = partial
                    await ws.send_json({"type": "partial", "text": partial})
                if recognizer.is_endpoint(stream):
                    if partial:
                        await ws.send_json({"type": "segment", "text": partial})
                    last_partial = ""
                    stream = recognizer.create_stream()
    except Exception as exc:  # noqa: BLE001 —— 任何异常都要让客户端知道为何断
        logger.exception("流式转写连接异常")
        try:
            await ws.send_json({"type": "error", "reason": f"转写中断：{exc!r}"})
        except Exception:  # noqa: BLE001 —— 连接已死就不再挣扎
            pass
    finally:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    ctx, sid = _prepare(
        req.session_id, req.topic, req.our_side, req.opponent_text, req.domain
    )
    roster = load_roster()
    budget = config.ADVISOR_BUDGET_S if req.budget_s is None else req.budget_s
    # 落库由 mavis 插件总线上的 LedgerPlugin 负责（见 observers.py）。
    # 同步阻塞调用放到线程池，避免堵住事件循环
    results, total = await asyncio.to_thread(
        run_advisors, ctx, roster, None, req.retry, budget,
        observers.build_manager(session_id=sid),
    )
    return AnalyzeResponse(
        session_id=sid, topic=ctx.topic, our_side=ctx.our_side,
        opponent_text=ctx.opponent_text, total_latency_s=total, results=results,
        our_ledger=ctx.our_ledger, prompt_pack=ctx.pack,
    )


@app.get("/api/analyze/stream")
async def analyze_stream(
    topic: str = Query(...),
    opponent_text: str = Query(...),
    our_side: str = Query(DEFAULT_SIDE),
    domain: str = Query(""),
    session_id: str | None = Query(None),
    retry: int = Query(2),
    budget_s: float | None = Query(None),
):
    """GET 版 SSE：先用 EventSource 的旧形态，保留给脚本与旧客户端。

    输入走 query 有两个天生缺陷（体检 2026-09-30 的 P2-1）：URL 长度受服务端
    请求行上限约束（实测 ~32KB，语音转写的长发言可能撞上），且全文会进
    访问日志。**前端已改用下面的 POST 版**，两者的事件序列完全一致。
    """
    return _analyze_stream_response(
        AnalyzeRequest(
            topic=topic, opponent_text=opponent_text, our_side=our_side,
            domain=domain, session_id=session_id, retry=retry, budget_s=budget_s,
        )
    )


@app.post("/api/analyze/stream")
async def analyze_stream_post(req: AnalyzeRequest):
    """POST 版 SSE：输入走 JSON body，事件序列与 GET 版完全一致。

    每完成一路推一条，最后推 done。browser 侧用 fetch 流式读取
    （EventSource 不支持 POST，这是当初 GET 的唯一理由——现已用
    自行解析 SSE 块取代它）。
    """
    return _analyze_stream_response(req)


def _analyze_stream_response(req: AnalyzeRequest) -> StreamingResponse:
    """GET / POST 两个形态共用的 SSE 组装。

    先推会话信息，再每完成一路参谋推一条，最后推 done。
    """
    ctx, sid = _prepare(
        req.session_id, req.topic, req.our_side, req.opponent_text, req.domain
    )
    roster = load_roster()
    budget = config.ADVISOR_BUDGET_S if req.budget_s is None else req.budget_s
    out_queue: queue.Queue = queue.Queue()

    def worker():
        # 落库 + 推流是两个独立观察者，任一个抛错都不影响另一个
        # （隔离由 mavis 的 PluginManager 逐插件 try/except 提供）
        manager = observers.build_manager(
            session_id=sid,
            out_queue=out_queue,
            done_payload={
                "label": "", "status": "ok", "session_id": sid,
                "our_ledger": ctx.our_ledger, "budget_s": budget, "kind": "meta",
            },
        )
        try:
            run_advisors(ctx, roster, retry=req.retry, budget_s=budget, plugins=manager)
        except Exception as exc:  # noqa: BLE001
            logger.exception("SSE worker 异常")
            out_queue.put({"advisor": "_error", "label": "系统", "status": "error",
                           "latency_s": 0.0, "error": repr(exc), "kind": "text"})
            # run_advisors 的 finally 会在正常路径推 _done；异常路径得自己补一条，
            # 否则前端会一直等下去
            out_queue.put({"advisor": "_done", "label": "", "status": "ok",
                           "session_id": sid, "our_ledger": ctx.our_ledger,
                           "budget_s": budget, "latency_s": 0.0, "kind": "meta"})

    threading.Thread(target=worker, daemon=True).start()

    async def event_gen():
        yield ": connected\n\n"
        yield (
            "event: session\ndata: "
            + json.dumps(
                {"session_id": sid, "our_ledger": ctx.our_ledger,
                 "advisors": [a.name for a in roster],
                 # 本轮用的是哪个提示词包：界面据此显示。
                 # 先告诉前端，再开始出结果 —— 让人一眼看到"这次按哪套措辞在问"，
                 # 而不是靠猜。包名由后端解析，前端不再复刻那份 domain→包的映射。
                 "prompt_pack": ctx.pack,
                 "pack_label": prompt_packs.label_of(ctx.pack)},
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


@app.get("/api/metrics")
async def metrics():
    """现场仪表：各路参谋的 P50 / P95 延迟与成功率（含 timeout / error 计数）。"""
    return {
        "budget_s": config.ADVISOR_BUDGET_S,
        "bridge": config.LLM_BRIDGE_URL,
        "advisors": store.latency_stats(),
    }


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


# --------------------------------------------------------------------------
# 法源检索与引用核验（阶段 4）
# 纯本地计算：本组接口**不调用任何 LLM**，零 API 消耗。
# --------------------------------------------------------------------------
@app.get("/api/retrieval")
async def retrieval_status(reload: bool = Query(False)):
    retriever = await asyncio.to_thread(retrieval_mod.get_retriever, reload)
    return retriever.stats()


@app.post("/api/session/{session_id}/verify-citations")
async def verify_citations(session_id: str, req: VerifyRequest):
    """抽取并核验引用。三级状态：已核验 / 存疑 / 未核验。

    不传 `texts` 时，自动取该会话里最新一轮的参谋产出。
    """
    texts = req.texts
    if not texts:
        snap = await asyncio.to_thread(store.snapshot, session_id)
        if not snap:
            return {"error": "session not found"}
        latest: dict[str, dict] = {}
        for s in snap.get("suggestions", []):
            latest.setdefault(s["advisor"], s)
        texts = [_flatten(s.get("payload")) for s in latest.values()]

    combined = "\n".join(t for t in texts if t)
    retriever = retrieval_mod.get_retriever()
    report = await asyncio.to_thread(retrieval_mod.verify_text, combined, retriever)
    return report.to_dict()


# --------------------------------------------------------------------------
# 复盘导出（阶段 5）
# --------------------------------------------------------------------------
def _report_or_404(session_id: str):
    """取复盘数据；会话不存在时返回一个 **404 响应**。

    不能返回 `{"error": ...}` 的 200 —— 前端 `.md` / `.docx` 是 `<a href>` 直接下载，
    200 会让浏览器存下一个扩展名是 .md/.docx、内容却是 JSON 报错的假文件。
    `.html` 分支早已回 404，这里补齐一致性。
    """
    data = report_mod.build_report(session_id)
    if not data:
        return None, Response(
            content=json.dumps({"error": "session not found"}),
            status_code=404,
            media_type="application/json",
        )
    return data, None


@app.get("/api/session/{session_id}/export.md")
async def export_markdown(session_id: str):
    data, err = _report_or_404(session_id)
    if err:
        return err
    text = report_mod.to_markdown(data)
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="ai-debater-{session_id}.md"'
        },
    )


@app.get("/api/session/{session_id}/export.docx")
async def export_docx(session_id: str):
    data, err = _report_or_404(session_id)
    if err:
        return err
    blob = await asyncio.to_thread(report_mod.to_docx, data)
    return Response(
        content=blob,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="ai-debater-{session_id}.docx"'
        },
    )


@app.get("/api/session/{session_id}/export.html", response_class=HTMLResponse)
async def export_html(session_id: str):
    """打印优化页面：前端打开它并唤起打印，用户在对话框里选「存储为 PDF」。

    为什么不直接生成 PDF：中文 PDF 需要内嵌 CJK 字体，缺字体会变成方块；
    浏览器打印用系统字体，零依赖且排版最好。详见 export/report.py 顶部说明。
    """
    data, err = _report_or_404(session_id)
    if err:
        return HTMLResponse("<h1>会话不存在</h1>", status_code=404)
    return HTMLResponse(report_mod.to_html(data))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level="info")
