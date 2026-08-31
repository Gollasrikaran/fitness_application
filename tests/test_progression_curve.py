"""Unit tests for the pure diminishing-curve formula (RLM design doc §4.1).

No DB dependency — compute_curve_increase is arithmetic only, per 15.5's
"deterministic and testable" requirement.
"""
from app.progression.service import compute_curve_increase


def test_week_zero_has_nothing_to_compare_against():
    """The entry's first week has no prior week — nothing to progress from yet."""
    assert compute_curve_increase(100.0, week=0, k=0.15) == 0.0


def test_negative_week_is_treated_like_week_zero():
    assert compute_curve_increase(100.0, week=-3, k=0.15) == 0.0


def test_increase_is_always_non_negative_for_positive_k():
    for week in range(1, 60):
        assert compute_curve_increase(100.0, week=week, k=0.15) >= 0.0


def test_increase_diminishes_as_week_grows():
    """Early weeks are largest, later weeks smaller — never flat, never negative."""
    early = compute_curve_increase(100.0, week=1, k=0.15)
    mid = compute_curve_increase(100.0, week=10, k=0.15)
    late = compute_curve_increase(100.0, week=50, k=0.15)
    assert early > mid > late > 0.0


def test_result_is_independent_of_baseline_target():
    """capacity(week)/capacity(week-1) is a ratio — baseline_target cancels out
    algebraically, so the same week/k must give the same pct regardless of scale."""
    a = compute_curve_increase(10.0, week=4, k=0.15)
    b = compute_curve_increase(10_000.0, week=4, k=0.15)
    assert round(a, 9) == round(b, 9)


def test_larger_k_means_larger_increase():
    small_k = compute_curve_increase(100.0, week=3, k=0.05)
    large_k = compute_curve_increase(100.0, week=3, k=0.30)
    assert large_k > small_k
