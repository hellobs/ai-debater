"""回归评估框架的单元测试（全部本地，零 API 消耗）。"""
from __future__ import annotations

from benchmarks.runner import (
    _focus_coverage,
    _pct,
    analyze_payload,
    compare,
    load_cases,
    validate_cases,
)


# --------------------------------------------------------------------------
# 用例
# --------------------------------------------------------------------------
def test_every_bundled_case_declares_legal_domain():
    """回归用例全是法学题 —— domain 必须显式声明并由 analyze_payload 透传。

    此前 run_live 不传 domain，法学用例全部跑在 general 提示词包上，
    回归指标测的不是法学措辞（2026-10-01 体检发现的系统性偏差）。
    """
    cases = load_cases()
    assert cases, "core.yaml 不应为空"
    for case in cases:
        assert case.get("domain") == "AI + 法学", f"{case['id']} 缺 domain"


def test_analyze_payload_carries_domain():
    case = {"id": "x", "topic": "T", "our_side": "S", "opponent_text": "O",
            "domain": "AI + 法学"}
    payload = analyze_payload(case, budget_s=30)
    assert payload["domain"] == "AI + 法学"
    assert payload["budget_s"] == 30
    # 缺 domain 的用例透传空串 → 后端落默认包（自由输入语义），不猜
    assert analyze_payload({"topic": "T", "our_side": "S", "opponent_text": "O"}, 30)["domain"] == ""


def test_bundled_cases_are_valid():
    cases = load_cases()
    assert len(cases) >= 4
    assert validate_cases(cases) == []


def test_validate_catches_missing_fields():
    bad = [{"id": "x", "topic": "T"}]                     # 缺 our_side / opponent_text
    errors = validate_cases(bad)
    assert any("our_side" in e for e in errors)
    assert any("opponent_text" in e for e in errors)


def test_validate_catches_duplicate_id():
    dup = [
        {"id": "a", "topic": "T", "our_side": "S", "opponent_text": "这是一段足够长的发言内容。"},
        {"id": "a", "topic": "T2", "our_side": "S", "opponent_text": "这是另一段足够长的发言内容。"},
    ]
    assert any("重复" in e for e in validate_cases(dup))


def test_validate_catches_too_short_opponent_text():
    bad = [{"id": "a", "topic": "T", "our_side": "S", "opponent_text": "太短"}]
    assert any("过短" in e for e in validate_cases(bad))


# --------------------------------------------------------------------------
# 指标计算
# --------------------------------------------------------------------------
def test_focus_coverage_math():
    cov = _focus_coverage("本案涉及独创性与法人作品", ["独创性", "法人作品", "目的解释"])
    assert cov["hits"] == 2 and cov["total"] == 3
    assert cov["rate"] == 0.667
    assert cov["missed"] == ["目的解释"]


def test_focus_coverage_empty_keywords():
    assert _focus_coverage("任意文本", [])["rate"] is None


def test_pct_handles_small_and_empty():
    assert _pct([], 50) is None
    assert _pct([1.0], 95) == 1.0
    assert _pct([1, 2, 3, 4, 5], 50) == 3
    assert _pct([1, 2, 3, 4, 5], 95) == 5


# --------------------------------------------------------------------------
# 对比
# --------------------------------------------------------------------------
def _row(syll, focus, cite, p50, p95):
    return {
        "structure": {"syllogism_rate": syll},
        "focus": {"rate": focus},
        "citations": {"verify_rate": cite},
        "latency": {"p50": p50, "p95": p95},
    }


def test_compare_labels_improvement_and_regression():
    before = _row(0.5, 0.4, 0.0, 2.0, 4.0)
    after = _row(1.0, 0.4, 0.0, 1.8, 5.5)
    text = "\n".join(compare(before, after))
    assert "三段论完整率" in text and "变好" in text      # 0.5 → 1.0 变好
    assert "P95 延迟(s)" in text and "变差" in text     # 4.0 → 5.5 变差
    assert "要点覆盖率" in text and "不变" in text      # 持平


def test_compare_reports_missing_data():
    before = _row(None, None, None, None, None)
    after = _row(1.0, 1.0, 1.0, 1.0, 1.0)
    text = "\n".join(compare(before, after))
    assert "数据不足" in text
