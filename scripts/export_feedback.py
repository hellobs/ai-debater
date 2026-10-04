#!/usr/bin/env python3
"""反馈 → 训练数据导出（反馈闭环的出口，纯本地，0 API 消耗）。

双门槛模仿样本（人工勾选 + 评分线）+ 偏好对（用户采纳版 vs 模型原文）。
门槛与格式说明见 app/feedback.py。

用法：
    .venv/Scripts/python.exe scripts/export_feedback.py                  # 默认 data/feedback/
    .venv/Scripts/python.exe scripts/export_feedback.py --out 路径.jsonl
    .venv/Scripts/python.exe scripts/export_feedback.py --min-rating 3
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.feedback import export  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="反馈/偏好对 → 训练 JSONL（0 消耗）")
    ap.add_argument("--out", default=str(ROOT / "data" / "feedback"
                                         / f"advisor-{datetime.now():%Y%m%d}.jsonl"))
    ap.add_argument("--min-rating", type=int, default=4)
    ap.add_argument("--no-pairs", action="store_true", help="不导偏好对")
    args = ap.parse_args()

    result = export(Path(args.out), min_rating=args.min_rating,
                    include_pairs=not args.no_pairs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n样本 {result['samples']} 条 → {result['out']}")
    if not args.no_pairs:
        print(f"偏好对 {result['pairs']} 条 → {Path(result['out']).with_suffix('.pairs.jsonl')}")
    if result["samples"] == 0 and result["pairs"] == 0:
        print("\n（还没有达标数据：在界面上给参谋打分并勾选「收录样本」，"
              "或采纳卡片后改笔，再来导出）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
