#!/usr/bin/env python3
"""把法律全文（txt/md）转成 `data/corpus/laws.json`，让引用核验能判「已核验」。

为什么需要它：核验的**唯一**依据是结构化语料里"条款号 → 原文"的对应关系。
手工拼 JSON 容易写错条款号，而这个脚本把「第X条」的切分交给程序做。

用法：
    # 单个文件（法名从正文猜，猜不到就用文件名）
    python scripts/import_corpus.py ~/downloads/著作权法.txt

    # 明确指定法名（推荐：核验时靠这个名字对齐）
    python scripts/import_corpus.py copyright.txt --law 中华人民共和国著作权法

    # 批量
    python scripts/import_corpus.py laws/*.txt --out data/corpus/laws.json

    # 只看解析结果，不写文件
    python scripts/import_corpus.py copyright.txt --dry-run

本脚本**不联网、不调用 LLM、不内置任何法条内容**——只做结构化。
法条来源：国家法律法规数据库 https://flk.npc.gov.cn
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.retrieval.statute_text import (  # noqa: E402
    StatuteParseError,
    article_no,
    parse_statute_text,
)

DEFAULT_OUT = ROOT / "data" / "corpus" / "laws.json"


def load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"[错误] 现有 {path} 不是合法 JSON：{e}\n       请先修复或加 --overwrite 重建。")
    if isinstance(data, list):
        sys.exit(
            f"[错误] 现有 {path} 是数组写法。本脚本只合并对象写法，"
            "请先加 --overwrite 重建（数组写法的内容请自行保留）。"
        )
    if not isinstance(data, dict):
        sys.exit(f"[错误] 现有 {path} 结构无法识别：{type(data).__name__}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(
        description="法律全文 → data/corpus/laws.json", formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("files", nargs="+", help="法律全文（.txt / .md）")
    ap.add_argument("--law", default="", help="法名；仅单文件时生效，留空则从正文猜")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"输出路径（默认 {DEFAULT_OUT}）")
    ap.add_argument("--dry-run", action="store_true", help="只解析并打印，不写文件")
    ap.add_argument("--overwrite", action="store_true", help="丢弃已有语料，只写本次结果")
    args = ap.parse_args()

    if args.law and len(args.files) > 1:
        sys.exit("[错误] --law 只能用于单文件（多文件请各自把法名写进正文首行）")

    out_path = Path(args.out)
    store = {} if args.overwrite else load_existing(out_path)

    parsed, failed = [], 0
    for i, f in enumerate(args.files):
        p = Path(f)
        if not p.exists():
            print(f"[跳过] 文件不存在：{p}", file=sys.stderr)
            failed += 1
            continue
        try:
            res = parse_statute_text(p.read_text(encoding="utf-8", errors="ignore"),
                                     law=args.law if i == 0 else "")
        except StatuteParseError as e:
            print(f"[失败] {p.name}：{e}", file=sys.stderr)
            failed += 1
            continue
        if not res.law:
            res.law = p.stem          # 兜底：用文件名
            res.warnings.append(f"法名取自文件名：{p.stem}（建议用 --law 指定准确名称）")
        print("  " + res.summary())
        parsed.append(res)

    if not parsed:
        sys.exit("[错误] 没有任何文件解析成功，未写入。")

    for res in parsed:
        store[res.law] = dict(sorted(res.articles.items(), key=lambda kv: article_no(kv[0])))

    total_articles = sum(len(v) for v in store.values())
    print(f"\n合计：{len(store)} 部法律 / {total_articles} 条")

    if args.dry_run:
        print("（--dry-run：未写文件）")
        return

    # 注意：**不要**用 json.dumps(sort_keys=True)——那会按字符串重排，
    # 把「第一条、第二条…第十条」排成「第一条、第三条、第二条…」，丢掉条号顺序。
    ordered = {law: store[law] for law in sorted(store)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已写入：{out_path}")
    print("重启后端或点前端「重载语料」即可让引用核验生效。")
    if failed:
        print(f"（有 {failed} 个文件失败，见上方 [失败]/[跳过]）", file=sys.stderr)


if __name__ == "__main__":
    main()
