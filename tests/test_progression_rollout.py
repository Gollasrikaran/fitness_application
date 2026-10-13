"""Phase 7 (Implementation_RLM_plan.md) — feature flags and guard-clamp
observability.

Two independent flags (config only, no DB migration needed — plain env vars
per app/platform/config.py's existing pattern):
- RLM_WEEKLY_PROGRESSION_ENABLED gates scripts/run_weekly_progression.py
- RLM_CHAT_ANALYSIS_ENABLED gates the chat-facing half (app/rag/service.py)

Guard-clamp logging goes through Python's logging (this codebase's existing
convention — see app/platform/redis_clients.py), not the AppIssue table,
which is explicitly scoped to genuine unexpected errors only (see the
_log_if_clamped docstring/comment in app/progression/service.py).
"""
import dataclasses
import logging
from decimal import Decimal

import app.rag.routes as rag_routes
from app.platform.db import session_scope
from app.profile import service as profile_service
from app.profile.models import UserProgram
from app.progression.service import apply_escalation, run_weekly_progression

ACTIVITY = "glute_bridge"


def _disable_chat_analysis(monkeypatch):
    """Builds a NEW Config via dataclasses.replace rather than mutating the
    shared session-scoped app's config object in place — Config is a frozen
    dataclass reused by every other test in this session, so mutating the one
    instance would leak this flag change into tests that run after this one."""
    orig_rag_config = rag_routes._rag_config
    monkeypatch.setattr(
        rag_routes, "_rag_config",
        lambda: dataclasses.replace(orig_rag_config(), rlm_chat_analysis_enabled=False),
    )


def test_chat_analysis_disabled_skips_performance_context_entirely(make_user, client, monkeypatch):
    """rlm_enabled=False must behave exactly as if Phase 4 never existed —
    no analyze_performance call, no performance block, falling through to the
    ordinary medical-only path unchanged. Goes through the real endpoint
    (rather than calling _retrieve_and_answer directly) so rag_db_url gets
    the same postgresql+psycopg:// -> postgresql:// conversion load_config()
    normally applies."""
    _disable_chat_analysis(monkeypatch)
    user = make_user()
    with session_scope() as s:
        profile_service.log_activity(s, user["user_id"], activity_type=ACTIVITY, amount=5, sets=2)

    r = client.post(
        "/v1/rehab/query", json={"question": "how am I doing with my glute bridges?"},
        headers=user["headers"],
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["needs_escalation_confirmation"] is False
    assert d["escalation_proposal"] is None


def test_escalation_confirmation_declines_when_chat_analysis_disabled(make_user, client, monkeypatch):
    """Even a well-formed confirmation tap must decline gracefully, never
    apply anything, while the flag is off."""
    _disable_chat_analysis(monkeypatch)
    user = make_user()

    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        before = float(entry.target_amount)

    r = client.post(
        "/v1/rehab/query",
        json={"escalation_confirmation": {"activity_type": ACTIVITY, "confirmed": True}},
        headers=user["headers"],
    )
    assert r.status_code == 200
    assert r.get_json()["escalation_applied"] is False

    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert float(entry.target_amount) == before


def test_weekly_progression_guard_clamp_is_logged(make_user, caplog):
    """Push an entry right up against its ceiling (per-user UserProgram data
    only — never mutate the shared, reviewed ActivityTaxonomy row, since that
    table is global and would leak into every other test using glute_bridge)
    so even the default curve's normal output overshoots the ceiling, and
    confirm the clamp produces a warning naming the activity.

    glute_bridge is reps-type, so at the default 2 sets its ceiling is the
    standard 30-reps-per-set ceiling (REPS_STANDARD_CEILING in service.py),
    not taxonomy.max_amount — see _reps_cycle_ceiling.

    Found live (test audit): the "curve" growth branch requires
    days_logged >= MIN_LOGGED_DAYS_FOR_GROWTH (3) — see run_weekly_progression
    — but this test only logged ONE day, so adherence was 100% yet
    days_logged stayed at 1, always falling through to the "hold" branch
    (raw_pct=0.0) instead of ever reaching the curve/clamp path at all. No
    growth was ever attempted, so nothing was ever clamped, so the warning
    this test checks for never fired — unrelated to any guard/clamp logic
    itself. Logging on 3 distinct days (still well inside the 7-day
    ADHERENCE_WINDOW_DAYS) satisfies the same gate run_weekly_progression
    itself requires."""
    from datetime import datetime, timedelta, timezone

    from app.profile import service as profile_service
    from app.profile.models import ActivityLog

    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.added_at = datetime.now(timezone.utc) - timedelta(days=8)  # week=1
        entry.target_sets = 2
        entry.target_amount = Decimal("28.00")  # volume=56, ceiling=30*2=60
        s.flush()
        # 100% adherence on 3 distinct days so this lands in the
        # curve-increase branch (MIN_LOGGED_DAYS_FOR_GROWTH).
        today = profile_service.today_ist()
        for i in range(3):
            s.add(ActivityLog(
                user_id=user["user_id"], activity_type=ACTIVITY, sets_done=2,
                amount_per_set=28, unit="count", total_volume=56,
                local_date=today - timedelta(days=i),
            ))
        s.flush()
        with caplog.at_level(logging.WARNING, logger="app.progression.service"):
            run_weekly_progression(s, user["user_id"])
    assert any(
        "progression guard clamped" in r.message and ACTIVITY in r.message
        for r in caplog.records
    )


def test_weekly_progression_no_log_when_nothing_needed_clamping(make_user, caplog):
    """The common case — no logs yet, so 0% adherence puts this in the <50%
    "reduce" band at a flat -10%, which is well within the per-adjustment cap
    and never clamped — must stay silent. This is a tuning signal, not
    routine noise; it should only fire when a guard actually changes the
    outcome."""
    from datetime import datetime, timedelta, timezone

    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.added_at = datetime.now(timezone.utc) - timedelta(days=8)
        s.flush()
        with caplog.at_level(logging.WARNING, logger="app.progression.service"):
            run_weekly_progression(s, user["user_id"])
    unclamped_rows = [r for r in caplog.records if ACTIVITY in r.message]
    assert unclamped_rows == []


def test_escalation_guard_clamp_is_logged(make_user, caplog):
    user = make_user()
    with session_scope() as s:
        with caplog.at_level(logging.WARNING, logger="app.progression.service"):
            apply_escalation(s, user["user_id"], ACTIVITY, proposed_pct_increase=3.0)  # +300%
    assert any(
        "progression guard clamped" in r.message and "escalation" in r.message
        for r in caplog.records
    )


def test_escalation_no_log_when_within_normal_step_choices(make_user, caplog):
    """A legitimate +5%/+10%/+15% proposal is never clamped in practice
    (all three are far under every guard) — confirms the log stays quiet for
    the actual, expected operating range, not just in theory."""
    user = make_user()
    with session_scope() as s:
        with caplog.at_level(logging.WARNING, logger="app.progression.service"):
            apply_escalation(s, user["user_id"], ACTIVITY, proposed_pct_increase=0.10)
    assert caplog.records == []
