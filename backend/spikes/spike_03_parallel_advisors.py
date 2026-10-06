"""阶段 0 · Spike C：降级方案验证——并行参谋团。

背景（Spike B 的结论）
----------------------
mavis 的 `Agent` 无法在不改源码的前提下被塑造成"参谋"：
  - `Agent.completion()` 只认框架写死的一组 `prompt_*`，没有"给建议"这一类；
  - `MAVIS_PROMPT_DIR` 只能换模板**文本**，换不了方法集合；
  - `think()` 是"日程→感知→定行动→移动→计划→反思"的生活仿真管线，
    产物是行动计划，不是建议文本；且要喂全 spatial tree + 真地图。

因此采用 PLAN §3.4 的降级方案：
  **只借 mavis 的公开 LLM 工厂 `create_llm_provider()`，并行编排用我们自己写。**
  依然一行不改 mavis。

本 spike 要证明：三路参谋并行跑，总耗时接近"最慢的一路"而非三者之和。
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import config  # noqa: E402
from mavisframework.runtime.llm import create_llm_provider  # noqa: E402

# 默认连**挂载式**桥（本进程 8010 的 /bridge/v1）—— 这是当前默认部署形态。
# 独立桥模式（python -m app.llm_bridge，默认 8011）请显式传 LLM_BRIDGE_URL。
# 模型复用 config.LLM_MODEL（单一来源），不再写死已下架的 deepseek-chat。
BRIDGE_URL = os.environ.get("LLM_BRIDGE_URL", "http://127.0.0.1:8010/bridge/v1")
MODEL = os.environ.get("LLM_MODEL", config.LLM_MODEL)

TOPIC = "AI 生成内容是否应享有著作权"
OUR_SIDE = "控方（主张：AI 生成内容应享有著作权）"
OPPONENT = (
    "著作权法只保护自然人的智力成果，AI 不是人，"
    "所以 AI 生成内容不应享有著作权。"
)

COMMON = f"""【辩题】{TOPIC}
【我方立场】{OUR_SIDE}
【对方刚说】{OPPONENT}
"""

ADVISORS = {
    "反驳手": COMMON + """
你是控方首席反驳手。请给出 2 条可以直接照着讲的反驳要点。
要求：每条不超过 80 字；必须针对对方论证的具体环节；不要复述对方原话。
只输出两条，用「1.」「2.」编号。
""",
    "质询手": COMMON + """
你是控方质询手。请给出 3 个可以立刻向对方抛出的质询问题。
要求：每个问题不超过 40 字；必须是对方难以两全的问题；不要解释原因。
只输出三个问题，用「1.」「2.」「3.」编号。
""",
    "逻辑审计员": COMMON + """
你是逻辑审计员。请指认对方论证中的逻辑谬误。
要求：指出谬误类型（如偷换概念/以偏概全/循环论证/诉诸权威），
并用一句话说明它出现在对方的哪个环节。不超过 60 字。
只输出一段。
""",
}


def main() -> int:
    llm = create_llm_provider({
        "provider": "openai",
        "model": MODEL,
        "base_url": BRIDGE_URL,
        "api_key": "",
        "cache": False,
        "concurrency": 4,
    })

    t0 = time.time()
    results: dict[str, tuple[float, str]] = {}

    def _run(name: str, prompt: str):
        start = time.time()
        out = llm.completion(prompt, retry=2)
        return name, time.time() - start, out

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(ADVISORS)) as pool:
        futures = [pool.submit(_run, n, p) for n, p in ADVISORS.items()]
        for fut in concurrent.futures.as_completed(futures):
            name, dt, out = fut.result()
            results[name] = (dt, out)

    total = time.time() - t0

    print(f"[spike C] 并行参谋团（{len(ADVISORS)} 路）")
    print("=" * 72)
    for name in ADVISORS:
        dt, out = results.get(name, (0.0, "<未返回>"))
        print(f"\n--- {name}（{dt:.2f}s）---")
        print((out or "").strip()[:400])
    print("\n" + "=" * 72)
    slowest = max((dt for dt, _ in results.values()), default=0.0)
    serial = sum(dt for dt, _ in results.values())
    print(f"[spike C] 总墙钟耗时 = {total:.2f}s")
    print(f"[spike C] 最慢一路   = {slowest:.2f}s")
    print(f"[spike C] 串行估算   = {serial:.2f}s")
    print(f"[spike C] 并行收益   = {serial - total:.2f}s"
          f"（{(1 - total / serial) * 100:.0f}% 节省）" if serial else "")
    print(f"[spike C] LLM 统计   = {json.dumps(llm.get_summary(), ensure_ascii=False)}")

    ok = sum(1 for _, out in results.values() if out and str(out).strip())
    print(f"[spike C] RESULT = {'PASS' if ok == len(ADVISORS) else f'PARTIAL({ok}/{len(ADVISORS)})'}")
    return 0 if ok == len(ADVISORS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
