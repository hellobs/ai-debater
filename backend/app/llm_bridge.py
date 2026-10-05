"""OpenAI 协议 -> Anthropic 协议 适配桥（阶段 0 地基）

为什么需要它
------------
mavis 的 LLM 层只会说 OpenAI 协议：
    POST {base_url}/chat/completions + Authorization: Bearer <key>
而本项目当前可用的网关只提供 Anthropic 协议：
    POST {base_url}/v1/messages + x-api-key + anthropic-version

本桥只做协议翻译，不含任何业务逻辑，也**不修改 mavis 一行代码**。
mavis 侧只需把 `think.llm.provider` 设为 `openai`，`base_url` 指向本桥。

安全红线
--------
上游凭据绝不写入文件、绝不回显、绝不打进日志。
初值来自环境变量；界面配置的那份由 `app/upstream.py` 在**内存里**改写本对象的
`CFG.base` / `CFG.token`（前后端分工见 upstream.py 的安全红线说明）。

两道防线（缺一不可，见 `_origin_allowed` 与 `_serving`）
-------------------------------------------------------
1. **来源校验**：跨站请求被拒（403）。
2. **在不在路径上**：只有 `anthropic` 形态下 mavis 才会指向本桥，其余形态 mavis 直连 ——
   这时桥握着云端凭据却毫无用处，正是"本机任意脚本 / curl 打过来就能烧额度"的残余面。
   不在路径上就**拒不服务**（503），请求在碰上游之前就被挡掉。
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import config  # 复用 config._env：空白值视为未设置，避免 int("") 在导入期崩

logger = logging.getLogger("llm_bridge")

class _BridgeConfig:
    """上游地址与凭据。**只内存**，运行期间可被改（后端把它 mount 进来后，
    由 `/api/upstream` 改 —— 见 app/upstream.py）。

    为什么不再是模块级常量：原先只能在**启动前**用环境变量定好，于是"换模型"
    要重启进程，界面上做不出一个下拉框。改成对象后，桥既能独立跑（初值仍来自
    环境变量，行为不变），也能被本进程内的后端重新指向另一个上游。

    红线不变：不写文件、不回显、不进日志（`healthz` 只报有没有配）。
    """

    __slots__ = ("base", "token")

    def __init__(self) -> None:
        self.base = config._env("ANTHROPIC_BASE_URL").rstrip("/")
        self.token = config._env("ANTHROPIC_AUTH_TOKEN")

    def configured(self) -> bool:
        return bool(self.base and self.token)


CFG = _BridgeConfig()

ANTHROPIC_VERSION = config._env("ANTHROPIC_VERSION", "2023-06-01")
DEFAULT_MODEL = config._env("LLM_MODEL", "deepseek-chat")
DEFAULT_MAX_TOKENS = int(config._env("LLM_BRIDGE_MAX_TOKENS", "2048"))
#: 桥对上游的超时。**必须 ≥ mavis 那层的单次调用上限（config.LLM_TIMEOUT_S）**：
#: 桥若先超时会返回空响应体，mavis 视为失败并 sleep(5) 重试——每次重试都真计费。
#: 此前这条约束只写在文档里（体检 2026-09-30 升级为代码保证）：取两者较大值。
_BRIDGE_TIMEOUT = float(config._env("LLM_BRIDGE_TIMEOUT", "120"))
TIMEOUT = max(_BRIDGE_TIMEOUT, float(config.LLM_TIMEOUT_S))

#: 允许调用本桥的来源主机名。
#: 为什么桥必须自己看来源：跨站请求**不需要 CORS 预检**就能打到它 —— 浏览器发
#: `Content-Type: text/plain` 的 POST 属于"简单请求"，用不上任何自定义头，所以
#: main.py 那条 `X-Debater-UI` 守卫（靠"自定义头强制预检"区分来源）挡不住它。
#: 体检实测（2026-10-04）：跨站 Origin 的 text/plain POST 确实带着 `x-api-key`
#: 转到了上游。桥被 main.py 整条豁免在守卫之外，纵深防御只能由桥自己做。
_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
#: 本地 vite dev server 的源（开发时也可能从浏览器直接打桥调试）
_ALLOWED_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})


def _origin_allowed(request: Request) -> bool:
    """来源校验：不带来源放行，带但非本机 / 本地开发源的拒绝。

    为什么"不带来源"要放行：正式调用方是 mavis **进程**，它用 httpx 发请求本就不带
    Origin（不是浏览器，没有 CORS 语义）；体检脚本与 curl 同理。会带 Origin 的只有
    浏览器 —— 而浏览器正是本机上唯一不该被信任的客户端。
    """
    raw = request.headers.get("origin") or request.headers.get("referer") or ""
    if not raw:
        return True
    if raw in _ALLOWED_ORIGINS:
        return True
    host = (urlparse(raw).hostname or "").lower()
    return host in _ALLOWED_HOSTS


def _serving() -> bool:
    """桥当前是不是**生效中的那条上游路径**（= 上游形态为 anthropic）。

    为什么要有这道：来源校验挡得住浏览器跨站，挡不住本机的 `curl` / 脚本 ——
    而"无来源放行"是 mavis 需要的形态。于是当上游根本不是 anthropic（本地 Ollama、
    OpenAI 兼容端点）时，桥握着云端凭据却**毫无用处**，正是体检留下的残余面：
    本机任何东西打过来都会带着那把 key 转上游。现在这种情况直接拒不服务。

    **问 `upstream` 模块而不是自己再推断一遍形态** —— 形态推断（含
    `:11434` 那个启发式）只在 `upstream._initial()` 一处，桥这边复刻一份必然对不上。
    判断不出来时一律按"不服务"：宁可误拒，也不能因为判断失败而放开。
    """
    try:
        from app import upstream

        return upstream.current().kind == "anthropic"
    except Exception:  # noqa: BLE001 - 判断失败 ≠ 放行
        logger.error("读不到当前上游形态，桥按「不在路径上」处理")
        return False


app = FastAPI(title="mavis llm protocol bridge")


def _split_messages(messages):
    """OpenAI messages -> (system 文本, Anthropic messages)"""
    system_parts, out = [], []
    for m in messages or []:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):
            content = "\n".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        content = content or ""
        if role == "system":
            system_parts.append(content)
        else:
            out.append({
                "role": "assistant" if role == "assistant" else "user",
                "content": content,
            })
    if not out:
        out = [{"role": "user", "content": ""}]
    return "\n\n".join(p for p in system_parts if p), out


def _json_instruction(response_format):
    """把 OpenAI 的 response_format 翻成一段"必须输出 JSON"的系统指令。

    为什么必须做这一步
    ------------------
    mavis 依赖结构化输出：它给每个 prompt 配了 pydantic `return_type`，
    发送 `response_format={"type":"json_schema", ...}`，然后解析返回的 JSON。
    Anthropic 协议没有 response_format 字段，如果直接丢掉，模型会回一段自然语言，
    mavis 解析失败后进入 10 次重试（每次 sleep 5s）——实测一步 think 因此烧掉 65 秒。
    所以必须把 schema 显式写进系统提示。
    """
    if not response_format:
        return ""
    if response_format.get("type") == "json_schema":
        spec = response_format.get("json_schema") or {}
        schema = spec.get("schema")
        if schema:
            props = list(((schema.get("properties") or {}).keys()))
            note = (
                "你必须只输出一个 JSON 对象，且严格符合下面的 JSON Schema。\n"
                "不要输出 markdown 代码块、不要解释、不要任何额外文字。\n"
            )
            if props:
                note += (
                    "顶层必须包含这些键："
                    + ", ".join(props)
                    + "。请勿省略外层包装，直接把内层内容当作顶层会使结果作废。\n"
                )
            note += (
                f"Schema 名称：{spec.get('name', 'Response')}\n"
                "JSON Schema：\n"
                + json.dumps(schema, ensure_ascii=False)
            )
            return note
    return "你必须只输出 JSON，不要输出任何额外文字。"


def _repair_json(text, response_format):
    """把模型输出修成 mavis 期望的 JSON 形状。

    为什么必须做
    ------------
    mavis 的每个 prompt 都配一个 pydantic 模型，且统一形如 `{"res": ...}`。
    实测中模型经常"太聪明"——直接把内层对象当顶层吐出来（丢掉 res 外壳），
    pydantic 校验随即失败，mavis 解析退化成一个字符串；
    紧接着 `schedule.update(<字符串>)` 抛 ValueError 直接崩掉一步 think。
    Anthropic 协议没有服务端强约束的结构化输出，所以这层修复只能放在桥里。

    返回：可用的 JSON 字符串；无法修复时返回原始文本（交给 mavis 自己的兜底）。
    """
    schema = ((response_format or {}).get("json_schema") or {}).get("schema") or {}
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    obj = None
    try:
        obj = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                obj = json.loads(match.group(0))
            except Exception:
                obj = None
    if obj is None:
        return text
    props = schema.get("properties") or {}
    if isinstance(obj, dict) and "res" in props and "res" not in obj:
        obj = {"res": obj}
    return json.dumps(obj, ensure_ascii=False)


def _anthropic_payload(body):
    system, messages = _split_messages(body.get("messages"))
    json_note = _json_instruction(body.get("response_format"))
    if json_note:
        system = (system + "\n\n" + json_note) if system else json_note
    payload = {
        "model": body.get("model") or DEFAULT_MODEL,
        "max_tokens": int(body.get("max_tokens") or DEFAULT_MAX_TOKENS),
        "messages": messages,
    }
    if body.get("temperature") is not None:
        payload["temperature"] = body["temperature"]
    if system:
        payload["system"] = system
    return payload


def _extract_text(data):
    parts = data.get("content") or []
    return "".join(
        p.get("text", "")
        for p in parts
        if isinstance(p, dict) and p.get("type") == "text"
    )


#: 桥向上游失败时，写进 OpenAI 响应体 content 的哨兵前缀。
#:
#: 为什么需要它：mavis 的 `OpenAIProvider._chat` **不检查 HTTP 状态码**，
#: 只读 `choices[0].message.content`。桥在失败时若只回一个空 content，
#: 这条失败会被 mavis 当成"模型正常答了空"，一路走到 `status="empty"` ——
#: 界面上显示「未返回内容。」且**没有任何错误提示**，真因只在后端日志里。
#: 塞一个可识别的哨兵进去，`mavis_bridge.complete()` 就能把它翻成
#: `status="error"`，把"上游挂了"与"模型答空"分开。
BRIDGE_ERROR_PREFIX = "__BRIDGE_ERROR__"


def _bridge_failure(reason: str, model: str, status_code: int) -> JSONResponse:
    """上游失败时的统一响应。

    两条不能破的性质：

    1. **body 仍是合法的 OpenAI 响应体。** mavis 对**非 JSON** 的响应会走
       10 次重试 × `sleep(5)` = 50 秒静默失败（实测一次 64.9s / 12 次调用），
       所以失败时也必须给 JSON。注意这条约束管的是 **body**，不是状态码 ——
       `requests` 不会因 4xx/5xx 抛异常，mavis 也从不读状态码。
    2. **content 里带 `BRIDGE_ERROR_PREFIX`**，让调用方能分辨出这是失败。

    状态码如实反映失败（此前一律 200，脚本与 curl 完全看不出来）。
    """
    return JSONResponse(
        _openai_body(f"{BRIDGE_ERROR_PREFIX} {reason}", model),
        status_code=status_code,
    )


def _openai_body(text, model):
    """构造 mavis 期望的 OpenAI 响应体。

    注意：mavis 的 OpenAIProvider **不检查 HTTP 状态码**，只读
    data["choices"][0]["message"]["content"]。所以出错时也必须返回合法 JSON，
    否则它会走 10 次重试 + 每次 sleep(5s)，把失败拖成 50 秒静默。
    """
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {},
    }


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        #: 桥是不是生效中的上游路径。不是 ⇒ /v1/chat/completions 会一律 503。
        #: 排查"为什么桥不响应"先看这个字段（它比 upstream_host 更早说明原因）。
        "serving": _serving(),
        "upstream_configured": CFG.configured(),
        "upstream_host": CFG.base.split("//")[-1].split("/")[0] if CFG.base else "",
        "default_model": DEFAULT_MODEL,
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    # 第一道门：不在路径上就拒不服务（比来源校验更早，也更无条件 ——
    # 此时既没读 body 也没碰上游，一次额度都不花）。
    if not _serving():
        logger.warning("桥不在当前上游路径上（上游形态不是 anthropic），已拒绝调用")
        return JSONResponse(
            {"error": "桥未启用：当前上游不是 Anthropic 协议，mavis 走直连，"
                       "本桥不受理请求（这样也避免本机脚本借它烧额度）"},
            status_code=503,
        )
    body = await request.json()
    if not _origin_allowed(request):
        # 关键点：此时还没碰上游 —— 跨站调用一次额度都不花（体检发现的漏洞，当场补上）
        logger.warning("拒绝跨站调用：origin=%s",
                       request.headers.get("origin") or request.headers.get("referer") or "-")
        return JSONResponse(
            {"error": "跨站调用被拒绝：本桥只接受本机与本地开发来源"
                       "（正式调用方 mavis 是服务端进程，不带 Origin）"},
            status_code=403,
        )
    payload = _anthropic_payload(body)
    if not CFG.configured():
        logger.error("上游未配置：ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN 缺失")
        return _bridge_failure(
            "上游未配置（ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN 缺失）",
            payload["model"], 503,
        )

    headers = {
        "x-api-key": CFG.token,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{CFG.base}/v1/messages", json=payload, headers=headers
            )
        if resp.status_code != 200:
            logger.error("上游 HTTP %s：%s", resp.status_code, resp.text[:300])
            return _bridge_failure(f"上游 HTTP {resp.status_code}", payload["model"], 502)
        text = _extract_text(resp.json())
        if body.get("response_format"):
            text = _repair_json(text, body.get("response_format"))
    except Exception as exc:  # noqa: BLE001 - 桥必须永不抛给调用方
        logger.error("上游调用失败：%r", exc)
        return _bridge_failure(
            f"上游调用失败：{type(exc).__name__}", payload["model"], 502
        )

    logger.info(
        "bridge ok model=%s latency=%.2fs chars=%d",
        payload["model"], time.time() - started, len(text),
    )
    return JSONResponse(_openai_body(text, payload["model"]))


def main():
    import uvicorn

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    host = config._env("LLM_BRIDGE_HOST", "127.0.0.1")
    port = int(config._env("LLM_BRIDGE_PORT", "8011"))
    logger.info("LLM 协议桥启动：http://%s:%s （上游=%s）", host, port,
                CFG.base.split("//")[-1].split("/")[0] or "未配置")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
