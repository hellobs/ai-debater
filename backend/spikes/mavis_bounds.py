"""实测 mavis 的几处边界行为，为 docs/mavis-gap-report.md 提供证据。

只读：不改 mavis 任何文件，只构造实例并观察。

    .venv/Scripts/python.exe backend/spikes/mavis_bounds.py          # 人读
    .venv/Scripts/python.exe backend/spikes/mavis_bounds.py --json   # 机器读

报告里每条编号（G1–G12 / N1–N6）都对应这里的一个探针 ——
这个脚本是那些结论的**复现入口**，不是装饰。

设计约束（与仓库其它部分同一条原则）：**证据只写一份**。
每个探针先算出结论与证据文本，再由 `main()` 决定渲染成人读格式还是 JSON；
`tests/test_mavis_gap_report.py` 消费的是同一份结构。
"打印一套、断言另一套"是这里明确要避免的。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time as _time

from mavisframework.runtime.llm_providers import OpenAIProvider, _BaseProvider

CFG = {"provider": "openai", "model": "m", "base_url": "http://127.0.0.1:1/v1",
       "api_key": "", "cache": True, "concurrency": 4}


# ==========================================================================
# 探针
#
# 每个探针返回:
#     {"id", "kind": "gap"|"note", "title", "severity"?, "category"?,
#      "reproduced": bool, "evidence": [str, ...]}
#
# `reproduced` 是**结论字段**：True 表示报告所述现象仍然成立。
# 它是给测试用的，人读输出不打印它 —— 人读的是 evidence。
# ==========================================================================
def g1_cache_whitelist() -> dict:
    """G1：结果缓存的调用名白名单写死，接入方登记不进自己的确定性调用。"""
    calls = {"n": 0}

    class P(OpenAIProvider):
        def _chat(self, messages, temperature, response_format=None):
            calls["n"] += 1
            return "ANSWER"

    whitelist = sorted(_BaseProvider._CACHEABLE_CALLERS)
    observed = {}
    for caller in ("poignancy_chat", "rebutter"):
        p = P(dict(CFG))
        calls["n"] = 0
        p.completion("同一个 prompt", caller=caller)
        p.completion("同一个 prompt", caller=caller)
        observed[caller] = {"upstream_calls": calls["n"], "cache": p.cache_stats()}

    inside, outside = observed["poignancy_chat"], observed["rebutter"]
    return {
        "id": "G1",
        "kind": "gap",
        "title": "结果缓存的调用名白名单写死",
        "category": "可用性",
        "severity": "中",
        "reproduced": inside["upstream_calls"] == 1 and outside["upstream_calls"] == 2,
        "evidence": [
            f"白名单: {whitelist}",
            f"caller='poignancy_chat' 同 prompt 调两次 → 上游被调 {inside['upstream_calls']} 次"
            f"；cache_stats={inside['cache']}",
            f"caller='rebutter'       同 prompt 调两次 → 上游被调 {outside['upstream_calls']} 次"
            f"；cache_stats={outside['cache']}",
        ],
    }


def g2_semaphore() -> dict:
    """G2：全局并发闸是类属性，`size` 一变就整体重建。"""
    _BaseProvider._GLOBAL_SEM = None
    a = _BaseProvider._semaphore(4)
    b = _BaseProvider._semaphore(4)
    _BaseProvider._semaphore(8)
    d = _BaseProvider._semaphore(4)
    same_size_same_object = a is b
    survives_size_change = a is d
    return {
        "id": "G2",
        "kind": "gap",
        "title": "全局并发闸是类属性，size 一变就整体重建",
        "category": "正确性",
        "severity": "高",
        "reproduced": same_size_same_object and not survives_size_change,
        "evidence": [
            f"同 size 两次是同一对象：{same_size_same_object}",
            f"换成 8 再回到 4，还是当初那个吗：{survives_size_change}"
            "   ← False 表示两个不同 concurrency 的 provider 会互相顶掉闸门",
        ],
    }


def g3_retry_semantics() -> dict:
    """G3：异常全吞 + 退避 `sleep(5)` 硬编码。"""
    rows = []
    for failsafe in (None, "SENTINEL"):
        calls = {"n": 0}
        slept: list = []
        real_sleep, _time.sleep = _time.sleep, slept.append

        class P(OpenAIProvider):
            def _chat(self, messages, temperature, response_format=None):
                calls["n"] += 1
                raise ConnectionError("upstream down")

        try:
            p = P(dict(CFG))
            out = p.completion("x", retry=3, caller="rebutter", failsafe=failsafe)
            rows.append({"failsafe": failsafe, "returned": out, "calls": calls["n"],
                         "sleeps": list(slept)})
        finally:
            _time.sleep = real_sleep

    return {
        "id": "G3",
        "kind": "gap",
        "title": "异常全吞 + 退避硬编码",
        "category": "可用性 / 可观测性",
        "severity": "中",
        # 现象成立的条件：无论传不传哨兵，重试次数都是 retry，退避都是写死的 5s
        "reproduced": all(r["calls"] == 3 and r["sleeps"] == [5, 5, 5] for r in rows),
        "evidence": [
            f"failsafe={r['failsafe']!r:<10} → 返回 {r['returned']!r:<10}"
            f" 上游被调 {r['calls']} 次（=retry），退避 sleep 参数 {r['sleeps']}"
            for r in rows
        ],
    }


def g4_top_level_exports() -> dict:
    """G4：`Scratch` / `Plugin` / `PluginManager` 未进顶层 `__all__`。"""
    import mavisframework

    exported = set(mavisframework.__all__)
    names = ("Scratch", "Plugin", "PluginManager")
    absent = [n for n in names if n not in exported and not hasattr(mavisframework, n)]
    return {
        "id": "G4",
        "kind": "gap",
        "title": "prompt / plugin 没进顶层 __all__",
        "category": "可用性",
        "severity": "中",
        "reproduced": len(absent) == len(names),
        "evidence": [
            *[f"{n:<14} 在顶层 __all__ 里：{n in exported}"
              f"；顶层直接可访问：{hasattr(mavisframework, n)}" for n in names],
            "但两个子包各自声明为公开面："
            " mavisframework.prompt.__all__ = ['Scratch','Result']；"
            " plugin.py 模块头写明是通用扩展面",
        ],
    }


def g5_validate_message() -> dict:
    """G5：`validate_message()` 与 `PluginManager.emit()` 契约不一致。"""
    from mavisframework import validate_message

    verdicts = {t: validate_message({"type": t})
                for t in ("snapshot", "chat_line", "advisor_result")}
    return {
        "id": "G5",
        "kind": "gap",
        "title": "validate_message() 与 PluginManager.emit() 契约不一致",
        "category": "文档",
        "severity": "低",
        "reproduced": (verdicts["snapshot"] and verdicts["chat_line"]
                       and not verdicts["advisor_result"]),
        "evidence": [
            *[f"validate_message({{'type': {t!r}}}) → {v!r}" for t, v in verdicts.items()],
            "注意：返回 bool，不抛异常。而 PluginManager.emit() 完全不校验，任意 dict 都播",
        ],
    }


def g6_scratch_isolation() -> dict:
    """G6：`Scratch` 的模板目录在构造时固化成实例属性。"""
    from mavisframework.prompt import Scratch

    tmp = tempfile.mkdtemp(prefix="mavis-tmpl-")
    probe = os.path.join(tmp, "probe.txt")
    prev_dir = os.environ.get("MAVIS_PROMPT_DIR")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("V1")

    os.environ["MAVIS_PROMPT_DIR"] = tmp
    s1 = Scratch(name="x", currently="", config={})
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("V2")
    body_is_reread = s1.build_prompt("probe", {}) == "V2"

    # 换目录后实例仍指着老目录 ⇒ 目录在构造时就被固化
    os.environ["MAVIS_PROMPT_DIR"] = os.path.dirname(tmp)
    dir_is_frozen = s1.template_path == tmp

    if prev_dir is None:
        os.environ.pop("MAVIS_PROMPT_DIR", None)
    else:
        os.environ["MAVIS_PROMPT_DIR"] = prev_dir

    return {
        "id": "G6",
        "kind": "gap",
        "title": "Scratch 的模板目录在构造时固化成实例属性",
        "category": "人体工程",
        "severity": "低",
        "reproduced": body_is_reread and dir_is_frozen,
        "evidence": [
            f"改完文件内容后 build_prompt → {'V2' if body_is_reread else '（未重读）'}"
            "（=V2：文件每次重读，改措辞不用重启）",
            f"改环境变量后 template_path 仍是 → {s1.template_path}"
            "（目录冻结，换目录得重建实例）",
            "构造签名 (name, currently, config, timer=None) —— build_prompt 一个都不用",
        ],
    }


def g7_summary_semantics() -> dict:
    """G7：`get_summary()` 的 `R` 不是"重试次数"，且异常尝试不计入。"""
    class Ok(OpenAIProvider):
        def _chat(self, messages, temperature, response_format=None):
            return "OK"

    class Boom(OpenAIProvider):
        def _chat(self, messages, temperature, response_format=None):
            raise ConnectionError("down")

    real_sleep, _time.sleep = _time.sleep, lambda s: None
    try:
        p_ok = Ok(dict(CFG))
        p_ok.completion("x", retry=3, caller="rebutter")
        ok_summary = p_ok.get_summary()["summary"]["rebutter"]

        p_boom = Boom(dict(CFG))
        p_boom.completion("x", retry=3, caller="rebutter")
        boom_summary = p_boom.get_summary()["summary"]["rebutter"]
    finally:
        _time.sleep = real_sleep

    r_ok = _parse_r(ok_summary)
    r_boom = _parse_r(boom_summary)
    return {
        "id": "G7",
        "kind": "gap",
        "title": "get_summary() 的 R 不是'重试次数'，且异常尝试不计入",
        "category": "可观测性",
        "severity": "中",
        # 现象成立的条件：成功时 R 计入，3 次异常后 R 仍是 0
        "reproduced": r_ok == 1 and r_boom == 0,
        "evidence": [
            f"一次成功                 → {ok_summary}   （R=完成的请求数）",
            f"3 次异常后放弃（retry=3） → {boom_summary}   ← 实际发了 3 次请求，R 却是 0",
            "结论：S/(S+F) 可当成功率；R 不能当'尝试总数'用。",
        ],
    }


def n1_failsafe_semantics() -> dict:
    """N1：不传 `failsafe` 时，"上游挂了"与"模型答空"的区分是偶然的。

    本条不是缺口（参数已存在于签名，属"用对即无问题"），但**必要性未被文档提示**。
    实测要说清的正是这个分寸：默认 `None` 下两类失败并非完全同形
    （`None` vs `''`），但这个差别是"实现细节的副产品"——
    任何按 `if not out` 归并空值的调用方都会把两者混为一谈。
    传哨兵之后，"上游重试耗尽"才成为一个**可比较的身份**。
    """
    class Down(OpenAIProvider):
        def _chat(self, messages, temperature, response_format=None):
            raise ConnectionError("upstream down")

    class Empty(OpenAIProvider):
        def _chat(self, messages, temperature, response_format=None):
            return ""

    real_sleep, _time.sleep = _time.sleep, lambda s: None
    try:
        observed = {}
        for label, cls in (("upstream_error", Down), ("empty_content", Empty)):
            for fs in (None, "SENTINEL"):
                p = cls(dict(CFG))
                observed[(label, fs)] = p.completion("x", retry=1, caller="rebutter",
                                                     failsafe=fs)
    finally:
        _time.sleep = real_sleep

    err = observed[("upstream_error", None)]
    emp = observed[("empty_content", None)]
    sentinel = observed[("upstream_error", "SENTINEL")]

    return {
        "id": "N1",
        "kind": "note",
        "title": "failsafe 不传则无法分辨失败类型",
        "reproduced": err is None and emp == "" and sentinel == "SENTINEL" and emp != sentinel,
        "evidence": [
            f"failsafe=None：上游异常 → {err!r}；模型返回空串 → {emp!r}"
            "   ← 差别是 None / ''，属实现副产品",
            f"failsafe='SENTINEL'：上游异常 → {sentinel!r}；模型返回空串 → "
            f"{observed[('empty_content', 'SENTINEL')]!r}",
            "本项目的分类逻辑（advisors/base.py）："
            "`is_failed(out)` → error；`out is None or len(out) == 0` → empty",
            "⇒ 不传哨兵时，两条分支会把两类失败一并收进 empty",
        ],
    }


def n2_abc_surface() -> dict:
    """N2：抽象基类只声明 3 个方法，实现另有 2 个公开方法。"""
    from mavisframework.runtime.llm import LLMProvider

    declared = {n for n in dir(LLMProvider) if not n.startswith("_")}
    real = {n for n in dir(OpenAIProvider) if not n.startswith("_")}
    extra = real - declared
    return {
        "id": "N2",
        "kind": "note",
        "title": "抽象基类只声明 3 个方法，实现另有 2 个公开方法",
        "reproduced": {"cache_stats", "disable"} <= extra,
        "evidence": [
            f"LLMProvider 声明: {sorted(declared)}",
            f"实现多出来: {sorted(extra)}   ← 按契约编程拿不到 cache_stats / disable",
        ],
    }


def n3_substitute() -> dict:
    """N3：模板用 `Template.substitute`（非 safe），裸 `$` 会炸。"""
    from string import Template

    raised = {}
    for text in ("$undefined_var", "单价 $100"):
        try:
            Template(text).substitute({})
            raised[text] = None
        except Exception as exc:  # noqa: BLE001
            raised[text] = f"{type(exc).__name__}: {exc}"

    return {
        "id": "N3",
        "kind": "note",
        "title": "模板用 Template.substitute（非 safe），裸 $ 会炸",
        "reproduced": all(v is not None for v in raised.values()),
        "evidence": [
            *[f"{t!r:<18} → {v or '（意外，没抛错）'}" for t, v in raised.items()],
            "结论：模板里写金额/公式要转义成 $$。好处是模板写错当场报，"
            "不会带着 $foo 进入提示词。",
        ],
    }


def n4_discover_needs_no_arg_factory() -> dict:
    """N4：`PluginManager.discover()` 仅自动实例化"可无参构造"的工厂。

    本案例三个观察者都需要 `session_id` / `out_queue`，因此不走入口点发现，
    改由 `mount()` 手工挂载。这里只读地验证那条判定规则本身 ——
    不往 `PluginManager.REGISTRY` 里写任何东西。
    """
    from mavisframework.plugin import Plugin, _is_no_arg_constructible

    class NoArg(Plugin):
        name = "no-arg"

    class NeedsCfg(Plugin):
        name = "needs-cfg"

        def __init__(self, session_id):
            self.session_id = session_id

    no_arg_ok = _is_no_arg_constructible(NoArg)
    needs_cfg_ok = _is_no_arg_constructible(NeedsCfg)
    return {
        "id": "N4",
        "kind": "note",
        "title": "discover() 仅自动实例化可无参构造的工厂",
        "reproduced": no_arg_ok is True and needs_cfg_ok is False,
        "evidence": [
            f"无参工厂   NoArg      → 可自动实例化：{no_arg_ok}",
            f"带必传参数 NeedsCfg(session_id) → 可自动实例化：{needs_cfg_ok}"
            "   ← 会在 discover() 里被跳过并告警",
            "本案例三个观察者均需 session_id / out_queue ⇒ 改为 mount() 手工挂载（见 observers.py）",
        ],
    }


# ==========================================================================
# 编排
# ==========================================================================

# ==========================================================================
# 第二轮探针（2026-10-01）：G8–G13 / N5–N6
# 判据不变：正确性缺口须复现；理论性风险走接线注意并如实标注"未复现"。
# ==========================================================================
def g8_http_status_ignored() -> dict:
    """G8：上游返回非 200 时状态码被无视，错误页直接进 JSON 解析器。"""
    import http.server
    import threading

    hits = {"n": 0}

    class Err(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            hits["n"] += 1
            body = b"<html><h1>upstream exploded</h1></html>"
            self.send_response(500)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Err)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real_sleep, _time.sleep = _time.sleep, lambda s: None
    try:
        p = OpenAIProvider({**CFG, "base_url": f"http://127.0.0.1:{srv.server_address[1]}/v1"})
        out = p.completion("x", retry=2, caller="g8", failsafe="SENTINEL")
    finally:
        _time.sleep = real_sleep
        srv.shutdown()
    return {
        "id": "G8",
        "kind": "gap",
        "title": "上游状态码未检查：错误页被当 JSON 解析，错误信息丢失",
        "category": "可用性 / 可观测性",
        "severity": "中",
        "reproduced": hits["n"] == 2 and out == "SENTINEL",
        "evidence": [
            f"假上游 2 次均返回 HTTP 500 + HTML 错误页；mavis 照常请求 {hits['n']} 次"
            "（response.json() 抛 JSONDecodeError → 异常被吞 → 退避重试），最终返回哨兵"
            f" {out!r}，HTTP 500 这一事实在任何返回值里都看不到",
            "源码：OpenAIProvider._chat 对 requests.post 的返回直接 .json()，"
            "从不读 response.status_code",
        ],
    }


def g9_unknown_kwargs_poison_retry() -> dict:
    """G9：max_tokens 无法表达；作为 kwargs 传入则退化为静默重试循环。"""
    calls = {"n": 0}
    slept: list = []
    real_sleep, _time.sleep = _time.sleep, slept.append

    class P(OpenAIProvider):
        def _chat(self, messages, temperature, response_format=None):
            calls["n"] += 1
            return "ok"

    try:
        p = P(dict(CFG))
        out = p.completion("x", retry=2, caller="g9", failsafe="SENTINEL", max_tokens=512)
    finally:
        _time.sleep = real_sleep
    return {
        "id": "G9",
        "kind": "gap",
        "title": "输出长度（max_tokens）不可配置，错误 kwargs 退化为静默重试",
        "category": "可用性",
        "severity": "中",
        "reproduced": calls["n"] == 0 and slept == [5, 5] and out == "SENTINEL",
        "evidence": [
            "completion(..., max_tokens=512)：_chat 从未被执行（calls=0）——参数在"
            " _completion(prompt, return_type, temperature=0.5) 处 TypeError，"
            "被 completion 的全捕获当失败处理",
            f"实测：上游被调 {calls['n']} 次，退避 {slept}，返回 {out!r} ——"
            "一个拼对名字的合法参数不是被忽略，而是把整次调用变成 2 轮 sleep(5) 的空转",
        ],
    }


def g10_no_streaming() -> dict:
    """G10：无流式支持 —— token 级输出在公开接口上不可表达。"""
    import inspect

    src = inspect.getsource(OpenAIProvider._chat)
    sig = list(inspect.signature(_BaseProvider.completion).parameters)
    reproduced = ('"stream": False' in src) and ("stream" not in sig)
    return {
        "id": "G10",
        "kind": "gap",
        "title": "无流式支持：token 级输出不可表达",
        "category": "可用性",
        "severity": "中",
        "reproduced": reproduced,
        "evidence": [
            "OpenAIProvider._chat 的请求参数硬编码 \"stream\": False",
            f"_BaseProvider.completion 形参 {sig} —— 无 stream；返回值是 str，非迭代器",
            "后果：接入方只能做『整段完成后一次性交付』；ai-debater 的 SSE 是"
            "『每路参谋』粒度，无法细化到逐字",
        ],
    }


def g11_factory_closed() -> dict:
    """G11：provider 工厂封闭 —— 新协议必须改框架源码。"""
    import inspect

    from mavisframework.runtime.llm import create_llm_provider

    raised = None
    try:
        create_llm_provider({"provider": "anthropic"})
    except NotImplementedError as exc:
        raised = str(exc)
    src = inspect.getsource(create_llm_provider)
    reproduced = (raised is not None) and ("register" not in src)
    return {
        "id": "G11",
        "kind": "gap",
        "title": "provider 工厂封闭：if/elif 硬编码，无注册钩子",
        "category": "可用性",
        "severity": "中",
        "reproduced": reproduced,
        "evidence": [
            "create_llm_provider({'provider': 'anthropic'}) → NotImplementedError："
            f"{raised}",
            "工厂仅 if/elif 两个分支（ollama / openai），源码中不存在任何注册钩子 ——"
            "接入方要支持新协议只能改框架源码，与『不 fork 即可扩展』的框架定位冲突；"
            "ai-debater 为此被迫自建整个协议桥（llm_bridge.py）",
        ],
    }


def g12_framework_logger_pollutes_stdout() -> dict:
    """G12：框架 logger 直写 stdout，污染宿主进程的受控输出。"""
    import contextlib
    import io
    import logging as _logging

    real_sleep, _time.sleep = _time.sleep, lambda s: None
    # --json 模式为干净输出全局 logging.disable —— 而被测行为恰是"框架往外写日志"，
    # 所以本探针内部临时恢复日志，跑完还原（否则自己把自己要测的东西禁掉）。
    prev_disable = _logging.root.manager.disable
    lg = _logging.getLogger("framework.llm")
    lg.handlers.clear()
    buf = io.StringIO()
    try:
        _logging.disable(_logging.NOTSET)
        lg.setLevel(_logging.INFO)

        class P(OpenAIProvider):
            def _chat(self, messages, temperature, response_format=None):
                raise ConnectionError("upstream down")

        p = P(dict(CFG))
        with contextlib.redirect_stdout(buf):
            p.completion("x", retry=1, caller="g12", failsafe=None)
    finally:
        _logging.disable(prev_disable)
        _time.sleep = real_sleep
    leaked = buf.getvalue()
    return {
        "id": "G12",
        "kind": "gap",
        "title": "框架 logger 直写宿主 stdout",
        "category": "人体工程",
        "severity": "低",
        "reproduced": "LLM completion error" in leaked,
        "evidence": [
            "一次失败调用的 warning 被写进宿主进程的 stdout："
            f"{leaked.strip()[:80]!r}",
            "get_logger 的 StreamHandler 绑定 sys.stdout（runtime/logger.py）；"
            "ai-debater 的机器可读探针（--json）因此被迫先 logging.disable 才能输出干净 JSON",
        ],
    }


def n5_temperature_undocumented() -> dict:
    """N5：temperature 可经 **kwargs 透传生效，但抽象签名与文档均未记载。"""
    seen: list = []

    class P(OpenAIProvider):
        def _chat(self, messages, temperature, response_format=None):
            seen.append(temperature)
            return "ok"

    p = P(dict(CFG))
    p.completion("x", retry=1, caller="n5", temperature=0.2)
    return {
        "id": "N5",
        "kind": "note",
        "title": "temperature 可经 **kwargs 透传生效，但契约未记载",
        "reproduced": seen == [0.2],
        "evidence": [
            f"completion(..., temperature=0.2) → _chat 实收 temperature={seen}",
            "但 LLMProvider 抽象签名只写 prompt/retry/callback/failsafe/return_type/"
            "caller/**kwargs，**kwargs 里什么能传全靠读源码 —— ai-debater 因此从未敢调它",
        ],
    }


def n6_summary_increment_outside_semaphore() -> dict:
    """N6：summary 计数递增位于并发闸之外 —— 理论性竞态（本机未复现丢失）。"""
    import inspect

    src = inspect.getsource(_BaseProvider.completion)
    lines = src.splitlines()
    with_line = next(i for i, l in enumerate(lines) if "with sem:" in l)
    inc_line = next(i for i, l in enumerate(lines) if 'self._summary["total"][0] += 1' in l)
    with_indent = len(lines[with_line]) - len(lines[with_line].lstrip())
    inc_indent = len(lines[inc_line]) - len(lines[inc_line].lstrip())
    reproduced = inc_line > with_line and inc_indent <= with_indent
    return {
        "id": "N6",
        "kind": "note",
        "title": "summary 计数递增在并发闸之外（理论性竞态，未复现丢失）",
        "reproduced": reproduced,
        "evidence": [
            "源码顺序：`with sem:` 收缩到网络调用，`self._summary[...][0] += 1` 的缩进"
            "与之平级 —— 并发递增不受闸保护，非原子读改写",
            "本机实测 3 × 6400 次并发递增零丢失（CPython GIL 下窗口极小）——"
            "按『缺口须可复现』的纪律不立为缺口，仅记录：高并发接入方不应把"
            " get_summary() 当精确计量",
        ],
    }


PROBES = (
    g1_cache_whitelist,
    g2_semaphore,
    g3_retry_semantics,
    g4_top_level_exports,
    g5_validate_message,
    g6_scratch_isolation,
    g7_summary_semantics,
    g8_http_status_ignored,
    g9_unknown_kwargs_poison_retry,
    g10_no_streaming,
    g11_factory_closed,
    g12_framework_logger_pollutes_stdout,
    n1_failsafe_semantics,
    n2_abc_surface,
    n3_substitute,
    n4_discover_needs_no_arg_factory,
    n5_temperature_undocumented,
    n6_summary_increment_outside_semaphore,
)

_R_RE = re.compile(r"R:(\d+)")


def _parse_r(summary: str) -> int:
    """从 `S:1,F:0/R:1` 里取 R。"""
    m = _R_RE.search(summary)
    return int(m.group(1)) if m else -1


def collect() -> list:
    """跑完所有探针，返回结构化结果。**只读**，不产生任何上游调用。"""
    return [probe() for probe in PROBES]


def envelope(results: list) -> dict:
    import mavisframework

    return {
        "mavis_version": str(getattr(mavisframework, "__version__", "unknown")),
        "readonly": True,          # 探针不修改 mavis 任何文件
        "probe_count": len(results),
        "gaps": [r for r in results if r["kind"] == "gap"],
        "notes": [r for r in results if r["kind"] == "note"],
    }


def render(results: list) -> str:
    """人读格式。evidence 与 JSON 里的是同一批字符串。"""
    lines = []
    for r in results:
        lines.append(f"== {r['id']} {r['title']} ==")
        lines.extend(f"   {e}" for e in r["evidence"])
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="mavis 边界行为探针（只读，零上游调用）")
    ap.add_argument("--json", action="store_true", help="输出结构化结果，供测试消费")
    args = ap.parse_args(argv)

    if args.json:
        # mavis 的日志默认落在 stdout，会把 JSON 弄脏；机器读模式下不输出日志。
        logging.disable(logging.CRITICAL)

    results = collect()

    if args.json:
        print(json.dumps(envelope(results), ensure_ascii=False, indent=2))
    else:
        print(render(results), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
