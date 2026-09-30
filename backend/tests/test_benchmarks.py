"""回归评估框架的单元测试（全部本地，零 API 消耗）。"""
from __future__ import annotations

from benchmarks.runner import _focus_coverage, _pct, compare, load_cases, validate_cases


# --------------------------------------------------------------------------
# 用例
# --------------------------------------------------------------------------
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
