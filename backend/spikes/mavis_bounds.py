"""实测 mavis 的几处边界行为，为 docs/mavis-gap-report.md 提供证据。

只读：不改 mavis 任何文件，只构造实例并观察。

    .venv/Scripts/python.exe backend/spikes/mavis_bounds.py          # 人读
    .venv/Scripts/python.exe backend/spikes/mavis_bounds.py --json   # 机器读

报告里每条编号（G1–G7 / N1–N4）都对应这里的一个探针 ——
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
PROBES = (
    g1_cache_whitelist,
    g2_semaphore,
    g3_retry_semantics,
    g4_top_level_exports,
    g5_validate_message,
    g6_scratch_isolation,
    g7_summary_semantics,
    n1_failsafe_semantics,
    n2_abc_surface,
    n3_substitute,
    n4_discover_needs_no_arg_factory,
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
