"""守住 `docs/mavis-gap-report.md` 的结论仍然成立。

探针（`backend/spikes/mavis_bounds.py`）是那份报告的**复现入口**，
所以它既是给人跑的脚本，也是给测试消费的数据源。

为什么值得一条测试：报告是"对某个**具体版本**的评估"，它不是永真命题 ——
框架一旦修掉某处，报告就从"结论"退化成"过期说法"，而文档不会自己报错。
**同一事实在仓库出现两次以上就是缺陷温床**：这里让"报告说的"与"实测到的"
只有一个来源（探针），文档只是它的渲染。

跑在子进程里：探针会动 mavis 的**进程级**并发闸与 logging，
隔离开最干净；也顺带保证"探针本身能被单独运行"这条路径没坏。
全程不发任何上游请求（探针把 `_chat` 换成假实现 + 把 `sleep` 打桩）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SPIKE = BACKEND / "spikes" / "mavis_bounds.py"
REPORT = ROOT / "docs" / "mavis-gap-report.md"

GAP_IDS = [f"G{i}" for i in range(1, 8)]
NOTE_IDS = [f"N{i}" for i in range(1, 5)]


@pytest.fixture(scope="module")
def probe() -> dict:
    """跑一次探针（只读、零上游调用），拿结构化结果。"""
    proc = subprocess.run(
        [sys.executable, str(SPIKE), "--json"],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    assert proc.returncode == 0, f"探针退出码 {proc.returncode}\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def report_text() -> str:
    return REPORT.read_text(encoding="utf-8")


def test_probe_output_is_pure_json(probe):
    """`--json` 的输出必须能被直接解析 —— mavis 的日志默认落 stdout，别漏进来。"""
    assert probe["probe_count"] == len(GAP_IDS) + len(NOTE_IDS)
    assert probe["readonly"] is True
    assert probe["mavis_version"] != ""


def test_all_seven_gaps_still_reproduce(probe):
    """7 处缺口仍全部成立。哪一条被上游修掉了，这里会红。"""
    assert [g["id"] for g in probe["gaps"]] == GAP_IDS
    stale = [g["id"] for g in probe["gaps"] if not g["reproduced"]]
    assert not stale, f"报告仍列着，但已复现不出来：{stale}（框架可能已修）"


def test_all_four_wiring_notes_still_reproduce(probe):
    """4 条接线注意同样有复现入口 —— 报告里写了 N1–N4，就该条条查得到。"""
    assert [n["id"] for n in probe["notes"]] == NOTE_IDS
    stale = [n["id"] for n in probe["notes"] if not n["reproduced"]]
    assert not stale, f"接线注意已复现不出来：{stale}"


def test_every_probe_carries_evidence(probe):
    """结论字段之外，每条都要说得出"看到了什么" —— 否则只是一句断言。"""
    for item in probe["gaps"] + probe["notes"]:
        assert item["title"], item["id"]
        assert item["evidence"], item["id"]
        assert all(isinstance(line, str) and line.strip() for line in item["evidence"])


def test_report_lists_exactly_the_probed_ids(probe, report_text):
    """报告里的编号集合 == 探针的编号集合（多一个少一个都算漂移）。"""
    in_report = set(re.findall(r"\b([GN]\d)\b", report_text))
    probed = {i["id"] for i in probe["gaps"] + probe["notes"]}
    assert in_report == probed, (
        f"报告独有：{sorted(in_report - probed)}；探针独有：{sorted(probed - in_report)}"
    )


def test_gap_severity_in_the_probe_matches_the_report_table(probe, report_text):
    """严重度是判断，不是描述 —— 正因为它会被人改，才更需要两边对齐。

    读的是报告 §3.5 结果汇总表：`| 编号 | 缺口 | 类别 | 严重度 | 是否影响本案例 |`
    """
    graded = {}
    for line in report_text.splitlines():
        m = re.match(r"\|\s*(G\d)\s*\|(.+)\|\s*$", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4:
            graded[m.group(1)] = cells[3]
    assert graded, "没在报告里解析出严重度表 —— 表头或列序可能变了"

    probed = {g["id"]: g["severity"] for g in probe["gaps"]}
    mismatch = {k: (v, probed.get(k)) for k, v in graded.items() if probed.get(k) != v}
    assert not mismatch, f"报告与探针的严重度不一致（报告, 探针）：{mismatch}"
