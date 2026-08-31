"""End-to-end test for analyze_performance (design doc §5.3), including the
real router LLM call (_should_recurse) — hits the real OpenRouter API, same
convention as the rest of this suite (see tests/conftest.py). Slow by nature
of free-tier latency; this is one deliberately minimal test, not a matrix.
"""
import os

from app.platform.db import session_scope
from app.progression.analysis import MAX_SUBCHECKS, analyze_performance

ACTIVITY = "glute_bridge"


def test_analyze_performance_returns_the_full_schema_shape(make_user):
    user = make_user(condition_codes=["gout"])
    with session_scope() as s:
        result = analyze_performance(
            s, user["user_id"], ACTIVITY, "how am I doing with my glute bridges?",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    assert result["summary_signal"] in (
        "on_track", "ahead_of_plan", "plateaued", "behind", "discomfort_flagged",
    )
    assert isinstance(result["findings"], list)
    assert len(result["findings"]) <= MAX_SUBCHECKS
    checks = {f["check"] for f in result["findings"]}
    assert {"adherence_trend", "plateau", "streak", "discomfort", "vs_curve"} <= checks

    discomfort = next(f for f in result["findings"] if f["check"] == "discomfort")
    assert discomfort["available"] is False  # 14.6 isn't built — must stay honest about it

    assert result["condition_gate"] == {"checked": True, "cached": False, "safe": True}
    # No progression history seeded for this fresh user -> nothing to escalate from.
    assert result["escalation_proposal"] == {"eligible": False}
