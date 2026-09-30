"""实测 mavis 的几处边界行为，为 docs/mavis-gap-report.md 提供证据。

只读：不改 mavis 任何文件，只构造实例并观察。

    .venv/Scripts/python.exe backend/spikes/mavis_bounds.py

报告里每条编号（G1 / G2 / … / N3）都对应这里的一段输出 ——
这个脚本是那些结论的**复现入口**，不是装饰。
"""
from __future__ import annotations

import tempfile
import time as _time

from mavisframework.runtime.llm_providers import OpenAIProvider, _BaseProvider

CFG = {"provider": "openai", "model": "m", "base_url": "http://127.0.0.1:1/v1",
       "api_key": "", "cache": True, "concurrency": 4}


def g1_cache_whitelist():
    print("== G1 结果缓存的调用名白名单写死 ==")
    calls = {"n": 0}

    class P(OpenAIProvider):
        def _chat(self, messages, temperature, response_format=None):
            calls["n"] += 1
            return "ANSWER"

    print(f"   白名单: {sorted(_BaseProvider._CACHEABLE_CALLERS)}")
    for caller in ("poignancy_chat", "rebutter"):
        p = P(dict(CFG))
        calls["n"] = 0
        p.completion("同一个 prompt", caller=caller)
        p.completion("同一个 prompt", caller=caller)
        print(f"   caller={caller!r:<18} 同 prompt 调两次 → 上游被调 {calls['n']} 次"
              f"；cache_stats={p.cache_stats()}")


def g2_semaphore():
    print("\n== G2 全局并发闸是类属性，size 一变就整体重建 ==")
    _BaseProvider._GLOBAL_SEM = None
    a = _BaseProvider._semaphore(4)
    b = _BaseProvider._semaphore(4)
    _BaseProvider._semaphore(8)
    d = _BaseProvider._semaphore(4)
    print(f"   同 size 两次是同一对象：{a is b}")
    print(f"   换成 8 再回到 4，还是当初那个吗：{a is d}"
          "   ← False 表示两个不同 concurrency 的 provider 会互相顶掉闸门")


def g3_retry_semantics():
    print("\n== G3 异常全吞 + 退避硬编码 ==")
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
            print(f"   failsafe={failsafe!r:<10} → 返回 {out!r:<10}"
                  f" 上游被调 {calls['n']} 次（=retry），退避 sleep 参数 {slept}")
        finally:
            _time.sleep = real_sleep


def g4_top_level_exports():
    print("\n== G4 prompt / plugin 没进顶层 __all__ ==")
    import mavisframework

    exported = set(mavisframework.__all__)
    for name in ("Scratch", "Plugin", "PluginManager"):
        print(f"   {name:<14} 在顶层 __all__ 里：{name in exported}"
              f"；顶层直接可访问：{hasattr(mavisframework, name)}")
    print("   但两个子包各自声明为公开面："
          " mavisframework.prompt.__all__ = ['Scratch','Result']；"
          " plugin.py 模块头写明是通用扩展面")


def g5_validate_message():
    print("\n== G5 validate_message() 与 PluginManager.emit() 契约不一致 ==")
    from mavisframework import validate_message

    for type_name in ("snapshot", "chat_line", "advisor_result"):
        msg = {"type": type_name}
        print(f"   validate_message({{'type': {type_name!r}}}) → {validate_message(msg)!r}")
    print("   注意：返回 bool，不抛异常。而 PluginManager.emit() 完全不校验，任意 dict 都播")


def g6_scratch_isolation():
    print("\n== G6 Scratch 的模板目录在构造时固化成实例属性 ==")
    import os
    from mavisframework.prompt import Scratch

    tmp = tempfile.mkdtemp(prefix="mavis-tmpl-")
    probe = os.path.join(tmp, "probe.txt")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("V1")

    os.environ["MAVIS_PROMPT_DIR"] = tmp
    s1 = Scratch(name="x", currently="", config={})
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("V2")
    print(f"   改完文件内容后 build_prompt → {s1.build_prompt('probe', {})!r}"
          "（=V2：文件每次重读，改措辞不用重启）")
    os.environ["MAVIS_PROMPT_DIR"] = os.path.dirname(tmp)
    print(f"   改环境变量后 template_path 仍是 → {s1.template_path}"
          "（目录冻结，换目录得重建实例）")
    print("   构造签名 (name, currently, config, timer=None) —— build_prompt 一个都不用")


def n2_abc_surface():
    print("\n== N2 抽象基类只声明 3 个方法，实现另有 2 个公开方法 ==")
    from mavisframework.runtime.llm import LLMProvider

    declared = {n for n in dir(LLMProvider) if not n.startswith("_")}
    real = {n for n in dir(OpenAIProvider) if not n.startswith("_")}
    print(f"   LLMProvider 声明: {sorted(declared)}")
    print(f"   实现多出来: {sorted(real - declared)}"
          "   ← 按契约编程拿不到 cache_stats / disable")


def n3_substitute():
    print("\n== N3 模板用 Template.substitute（非 safe），裸 $ 会炸 ==")
    from string import Template

    for text in ("$undefined_var", "单价 $100"):
        try:
            out = Template(text).substitute({})
            print(f"   {text!r:<18} → {out!r}（意外，没抛错）")
        except Exception as exc:  # noqa: BLE001
            print(f"   {text!r:<18} → {type(exc).__name__}: {exc}")
    print("   结论：模板里写金额/公式要转义成 $$。好处是模板写错当场报，"
          "不会带着 $foo 进入提示词。")


def g7_summary_semantics():
    print("\n== G7 get_summary() 的 R 不是'重试次数'，且异常尝试不计入 ==")
    from mavisframework.runtime.llm_providers import OpenAIProvider

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
        print(f"   一次成功                 → {p_ok.get_summary()['summary']['rebutter']}"
              "   （R=完成的请求数）")

        p_boom = Boom(dict(CFG))
        p_boom.completion("x", retry=3, caller="rebutter")
        print(f"   3 次异常后放弃（retry=3） → {p_boom.get_summary()['summary']['rebutter']}"
              "   ← 实际发了 3 次请求，R 却是 0")
    finally:
        _time.sleep = real_sleep
    print("   结论：S/(S+F) 可当成功率；R 不能当'尝试总数'用。")


if __name__ == "__main__":
    g1_cache_whitelist()
    g2_semaphore()
    g3_retry_semantics()
    g4_top_level_exports()
    g5_validate_message()
    g6_scratch_isolation()
    g7_summary_semantics()
    n2_abc_surface()
    n3_substitute()
