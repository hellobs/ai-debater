"""导出物：**平台级**产物不能带任何一个领域的措辞。

为什么要单独守这一层
--------------------
领域措辞的泄漏路径此前查到三条（提示词包 / `schemas.py` 的字段描述 / 显示名），
`tests/test_prompt_packs.py` 守着前两条。**导出是第四处，也是最要命的一处** ——
它直接就是交到人手上的交付物。

2026-09-30 实测到的三处具体泄漏：

1. `report.py` 里有一份**写死的** `ADVISOR_TITLES`，把显示名又定义了一遍；
   于是 `advisors.yaml` 已把 strategist 改成领域中立的「论证策略师」之后，
   导出报告仍然印着「解释方法策略师」——改一处不算改完。
2. `KIND_TITLES["strategy"]` 与三个出口的空状态文案都写着「解释方法」。
3. 「使用提示」的一条写死了「**法源**引用 … **上庭前**请自行确认」，
   于是每一份**通用**辩题（如"大学应否把 AI 设为必修课"）的复盘都带着法庭措辞。

本文件守两件事：
  - **同一份措辞只有一处定义**（显示名来自名册，不另抄一份）；
  - 导出可以发出的**任何字符串常量**都与领域无关（AST 扫源码里的字符串字面量，
    跳过注释与 docstring —— 记录"这里曾经泄漏过"的注释本身需要出现这些词）。
"""
from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest

from app.export import report

REPORT_PY = Path(report.__file__)

#: 导出物里不该出现的领域措辞。比 `test_prompt_packs.LEGAL_WORDS` **更宽**：
#: 那边查的是"通用提示词包/schema 里不该有的词"，而导出是平台级产物，
#: 连「解释方法」这种"在 legal 包里完全合法"的词也不该出现
#: （它在通用辩题下就是错配的框架名）。「上庭 / 法庭」是场景词，同理。
DOMAIN_WORDS = (
    "法条", "法源", "法律涵摄", "法律效果", "法律解释", "解释方法",
    "法理", "判例", "合宪性", "上庭", "法庭", "法典",
)


# ---------------------------------------------------------------------------
# 显示名：单一来源
# ---------------------------------------------------------------------------
def test_advisor_titles_come_from_the_roster():
    """导出章节标题＝名册里的显示名。**不得另抄一份。**"""
    from app.advisors import load_roster

    expected = {a.name: (a.label or a.name) for a in load_roster()}
    assert report.advisor_titles() == expected


def test_advisor_titles_order_follows_the_roster():
    """顺序也要来自名册（＝界面列序），不在这里另排一遍。"""
    from app.advisors import load_roster

    assert list(report.advisor_titles()) == [a.name for a in load_roster()]


def test_advisor_titles_fall_back_instead_of_emptying_the_report(monkeypatch):
    """名册炸了也不能让导出变成空报告 —— 那比印错一个字严重得多。"""
    import app.advisors as advisors_pkg

    def boom():
        raise RuntimeError("名册读不出来")

    monkeypatch.setattr(advisors_pkg, "load_roster", boom)
    titles = report.advisor_titles()
    assert titles, "兜底名表不能为空"
    assert set(titles) >= {"rebutter", "questioner", "auditor", "strategist", "risk"}


# ---------------------------------------------------------------------------
# 固定文案：领域中立，且同一条只有一处定义
# ---------------------------------------------------------------------------
def test_kind_titles_are_domain_neutral():
    blob = "\n".join(report.KIND_TITLES.values())
    hits = [w for w in DOMAIN_WORDS if w in blob]
    assert not hits, f"KIND_TITLES 里出现领域措辞：{hits}"


def test_fallback_titles_are_domain_neutral():
    blob = "\n".join(report._FALLBACK_TITLES.values())
    assert not [w for w in DOMAIN_WORDS if w in blob]


def test_note_variants_are_derived_from_one_sentence():
    """三个出口的带格式变体必须来自同一句，别各改一半。"""
    plain = report.NOTE_UNVERIFIED
    assert report.NOTE_UNVERIFIED_MD.replace("**", "") == plain
    assert report.NOTE_UNVERIFIED_HTML.replace("<b>", "").replace("</b>", "") == plain
    assert not [w for w in DOMAIN_WORDS if w in plain]


# ---------------------------------------------------------------------------
# 源码级：导出发得出去的每一个字符串常量都不许带领域措辞
# ---------------------------------------------------------------------------
def _emittable_strings(tree: ast.AST) -> list[str]:
    """收集源码里的字符串常量，**跳过 docstring**。

    注释不是字符串常量，本就不在扫描范围；docstring 要跳过是因为
    "这里曾经泄漏过「法源引用 … 上庭前请自行确认」"这类说明必须能写下来。
    剩下的一律是可能被渲染进交付物的字面量（含 f-string 的静态片段）。
    """
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))

    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                out.append(node.value)
        # f-string 的静态片段（JoinedStr 里除 FormattedValue 外的字符串）
    return out


def test_no_domain_word_in_any_emittable_string():
    source = REPORT_PY.read_text(encoding="utf-8")
    strings = _emittable_strings(ast.parse(source))
    offenders = sorted({w for w in DOMAIN_WORDS for s in strings if w in s})
    assert not offenders, (
        f"{REPORT_PY.name} 里有 {len(strings)} 个字符串常量，其中出现领域措辞：{offenders}。"
        "导出是平台级产物，措辞必须与辩题领域无关。"
    )


def test_docx_note_paragraph_matches_the_shared_sentence():
    """Word 出口真的用了那一句（而不是又写了一遍）。"""
    pytest.importorskip("docx")
    from docx import Document

    data = {
        "session": {"id": "x", "topic": "T", "our_side": "S", "created_at": ""},
        "turns": [], "cards": [], "sections": [],
        "generated_at": "2026-01-01 00:00", "stats": {"turns": 0, "cards": 0, "standing": 0},
    }
    doc = Document(io.BytesIO(report.to_docx(data)))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert report.NOTE_UNVERIFIED in text
