"""同题换包实测：领域提示词包到底改变了什么。

背景
----
`prompts/packs/` 把领域措辞从代码里拆了出去（`legal` / `general` 两包）。
「拆开了」与「拆开之后产出有没有变好」是两件事 —— 本脚本实测后者。

做法：**同一道通用辩题、同一段对方发言，只换辩题的 `domain`**
（`domain` 是选包的唯一切入点，见 `app/prompt_packs.py`），
把两套措辞的产出并排打出来。这样包里措辞是**唯一变量**。

为什么不跑满五路
----------------
`auditor` / `questioner` 在两包内**逐字节相同**，跑它们只是白花钱。
真正有差异的只有三路：`rebutter` / `strategist` / `risk`。

用法
----
    # 只看提示词差异（0 上游调用，先跑这个）
    .venv/Scripts/python.exe backend/spikes/pack_quality.py --dry-run

    # 真跑（⚠️ 2 包 × 3 路 = 6 次上游调用，重试会叠加）
    .venv/Scripts/python.exe backend/spikes/pack_quality.py

⚠️ 不加 `--dry-run` 会**真实计费**。
上游凭据只从环境变量读（`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`），
本脚本不回显、不落盘、不写进任何产物。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.advisors import REGISTRY, preload                      # noqa: E402
from app.advisors.base import DebateContext, as_text            # noqa: E402

#: 两包内真正有差异的三路。改动这里请同步说明"为什么是这几路"。
TARGETS = ("rebutter", "strategist", "risk")

#: 对照用的 `domain` 值 —— 逐字取自 `configs/prompt-packs.yaml` 的 `domains`。
DOMAIN_GENERAL = "通用"
DOMAIN_LEGAL = "AI + 法学"

#: 用例：通用辩题（与领域无关），取自 `configs/topics.yaml`。
TOPIC = "大学应当把人工智能设为必修课"
OUR_SIDE = "正方（应当必修）"
OPPONENT = (
    "大学教育的价值在于通识与人格养成，把一门还在快速迭代的技术课设为必修，"
    "是用短期就业焦虑绑架四年学制。"
)

#: 用于粗看"法学框子有没有漏进通用辩题的产出"。只是计数，不是判分。
LEGAL_WORDS = ("法条", "法源", "法律涵摄", "法律效果", "法律解释", "法理", "判例", "合宪性")


def build_ctx(domain: str) -> DebateContext:
    return DebateContext(topic=TOPIC, our_side=OUR_SIDE,
                         opponent_text=OPPONENT, domain=domain)


def run_one(pack_label: str, domain: str, name: str) -> dict:
    """跑一路参谋，返回结构化结果（不打印，交给 main 排版）。"""
    ctx = build_ctx(domain)
    advisor = REGISTRY[name]()
    prompt = advisor.build_prompt(ctx)
    result = advisor.run(ctx)
    text = as_text(result)
    return {
        "pack": pack_label,
        "domain": domain,
        "advisor": name,
        "label": advisor.label,
        "pack_resolved": ctx.pack,
        "prompt_chars": len(prompt),
        "status": result.status,
        "latency_s": result.latency_s,
        "text": text,
        "legal_hits": [w for w in LEGAL_WORDS if w in text],
    }


def _rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def dry_run(combos: list[tuple[str, str]]) -> int:
    """只渲染提示词，不调模型。"""
    for pack_label, domain in combos:
        ctx = build_ctx(domain)
        _rule(f"pack={pack_label}  domain={domain!r}  ->  ctx.pack={ctx.pack!r}")
        for name in TARGETS:
            advisor = REGISTRY[name]()
            directive = advisor.role_directive(ctx.pack)
            task = advisor.task_block(ctx.pack)
            print(f"\n--- {name}（{advisor.label}） 角色指令 ---")
            print(directive)
            print(f"\n--- {name} 任务说明 ---")
            print(task)
    print("\n[dry-run] 以上为提示词全文。未产生任何上游调用。")
    return 0


def live_run(combos: list[tuple[str, str]], retry: int) -> int:
    """真跑。会产生计费调用。"""
    if not (os.environ.get("ANTHROPIC_BASE_URL")
            and os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("[中止] 上游凭据未就位（环境变量缺失）。本脚本只读环境变量，不回显其值。")
        return 2

    advisors = [REGISTRY[n]() for n in TARGETS]
    preload(advisors)                     # 启动自检：所有包 × 三路模板齐不齐

    jobs = [(pack_label, domain, name) for pack_label, domain in combos for name in TARGETS]
    print(f"开始跑 {len(jobs)} 次上游调用（{len(combos)} 个包 × {len(TARGETS)} 路；"
          f"retry={retry}，失败会叠加）……")
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futures = [ex.submit(run_one, p, d, n) for p, d, n in jobs]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
    return _report(results)


def _report(results: list[dict]) -> int:
    order = {p: i for i, p in enumerate(dict.fromkeys(r["pack"] for r in results))}
    results.sort(key=lambda r: (TARGETS.index(r["advisor"]), order[r["pack"]]))

    _rule(f"用例：{TOPIC}（domain 决定包，其余输入完全相同）")
    for adv in TARGETS:
        rows = [r for r in results if r["advisor"] == adv]
        if not rows:
            continue
        _rule(f"{adv}（{rows[0]['label']}）")
        for r in rows:
            print(f"\n########## 包 = {r['pack']}（ctx.pack={r['pack_resolved']!r}）  "
                  f"status={r['status']}  提示词 {r['prompt_chars']} 字  "
                  f"耗时 {r['latency_s']}s ##########")
            print(r["text"] or "（空）")
            if r["legal_hits"]:
                print(f"  ⚠️ 产出里出现法学词：{r['legal_hits']}")

    _rule("小结")
    for r in results:
        print(f"  {r['advisor']:12s} {r['pack']:8s} status={r['status']:6s} "
              f"{r['latency_s']:>5}s  法学词命中={len(r['legal_hits'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="同题换提示词包实测")
    ap.add_argument("--dry-run", action="store_true", help="只渲染提示词，0 上游调用")
    ap.add_argument("--retry", type=int, default=1, help="每次调用允许的重试次数（默认 1）")
    args = ap.parse_args(argv)

    combos = [("general", DOMAIN_GENERAL), ("legal", DOMAIN_LEGAL)]
    if args.dry_run:
        return dry_run(combos)
    return live_run(combos, retry=args.retry)


if __name__ == "__main__":
    raise SystemExit(main())
