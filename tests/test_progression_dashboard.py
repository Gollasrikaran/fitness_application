"""Phase 6 (Implementation_RLM_plan.md) — the dashboard percentage graph.
progression_series is purely additive/read-only: it never writes, just
reshapes what run_weekly_progression / apply_escalation already recorded.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.platform.db import session_scope
from app.profile import service as profile_service
from app.progression.models import ProgressionHistory
from app.progression.service import progression_series

ACTIVITY = "glute_bridge"


def _seed_row(session, user_id, activity_type, *, adherence, curve, old, new, reason, when):
    session.add(ProgressionHistory(
        user_id=user_id, activity_type=activity_type,
        old_target=Decimal(str(old)), new_target=Decimal(str(new)),
        adherence_pct=Decimal(str(adherence)), curve_pct=Decimal(str(curve)),
        reason=reason, applied_at=when,
    ))
    session.flush()


def test_empty_for_a_user_with_no_progression_history_yet(make_user):
    user = make_user()
    with session_scope() as s:
        assert progression_series(s, user["user_id"]) == []


def test_groups_points_by_activity_and_sorts_by_display_name(make_user):
    user = make_user()
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        _seed_row(s, user["user_id"], "glute_bridge", adherence=90, curve=10,
                  old=10, new=11, reason="curve", when=now - timedelta(days=7))
        _seed_row(s, user["user_id"], "dead_bug", adherence=85, curve=8,
                  old=8, new=8.6, reason="curve", when=now - timedelta(days=7))
        series = progression_series(s, user["user_id"])
        names = [s_["display_name"] for s_ in series]
        assert names == sorted(names)  # "Dead Bug" before "Glute Bridge"
        assert {s_["activity_type"] for s_ in series} == {"glute_bridge", "dead_bug"}


def test_points_are_ordered_oldest_first_and_carry_the_full_shape(make_user):
    user = make_user()
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        _seed_row(s, user["user_id"], ACTIVITY, adherence=90, curve=10,
                  old=10, new=11, reason="curve", when=now - timedelta(days=14))
        _seed_row(s, user["user_id"], ACTIVITY, adherence=60, curve=0,
                  old=11, new=11, reason="hold", when=now - timedelta(days=7))
        series = progression_series(s, user["user_id"])
        points = next(s_ for s_ in series if s_["activity_type"] == ACTIVITY)["points"]
        assert [p["reason"] for p in points] == ["curve", "hold"]
        assert points[0]["old_target"] == 10.0
        assert points[0]["new_target"] == 11.0
        assert points[1]["adherence_pct"] == 60.0


def test_weeks_parameter_caps_how_far_back_the_series_goes(make_user):
    user = make_user()
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        for i in range(5):
            _seed_row(s, user["user_id"], ACTIVITY, adherence=90, curve=5,
                      old=10 + i, new=11 + i, reason="curve",
                      when=now - timedelta(days=(5 - i) * 7))
        series = progression_series(s, user["user_id"], weeks=2)
        points = series[0]["points"]
        assert len(points) == 2
        # Keeps the MOST RECENT weeks, not the oldest.
        assert points[-1]["new_target"] == 15.0


def test_dashboard_summary_endpoint_includes_progression(make_user, client):
    user = make_user()
    r = client.get("/v1/dashboard/summary", headers=user["headers"])
    assert r.status_code == 200
    d = r.get_json()
    assert "progression" in d
    assert d["progression"] == []  # nothing recorded yet for a fresh user
