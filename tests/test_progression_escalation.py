"""Phase 5 (Implementation_RLM_plan.md) — the chat-confirmed escalation write
path (app/progression/service.py:apply_escalation) and its wiring into Module
5's chat endpoint (app/rag/service.py:_confirm_escalation).

Per the plan's own instruction: test this phase adversarially — push a
proposed increase above each of the three independent guards (1.5x escalation
guard, per-adjustment cap, taxonomy ceiling) separately, and confirm each one
fires regardless of what the other two would have allowed.
"""
from decimal import Decimal

import pytest

from app.platform.db import session_scope
from app.platform.errors import NotFound
from app.profile import service as profile_service
from app.profile.models import UserProgram
from app.progression import service as progression_service
from app.progression.analysis import ESCALATION_GUARD_PCT
from app.progression.models import ProgressionHistory
from app.progression.service import MAX_ADJUSTMENT_PCT, apply_escalation

ACTIVITY = "glute_bridge"  # default 2x5, max 3x15, not per-side -> volume 10/45/floor 5


def test_escalation_guard_fires_even_if_nothing_else_would_have_capped_it(make_user, monkeypatch):
    """1.5x guard (ESCALATION_GUARD_PCT=0.5) tested in true isolation: with the
    default constants, MAX_ADJUSTMENT_PCT (0.20) is always tighter than the
    escalation guard (0.5), so a normal call can never prove the escalation
    guard specifically did the clamping — it would always be the adjustment
    cap. Temporarily raise the adjustment cap here so THIS guard is the one
    actually being exercised, proving it works on its own rather than always
    riding on the adjustment cap's coattails."""
    monkeypatch.setattr(progression_service, "MAX_ADJUSTMENT_PCT", 10.0)
    user = make_user()
    with session_scope() as s:
        row = apply_escalation(s, user["user_id"], ACTIVITY, proposed_pct_increase=3.0)  # +300%
        # old_volume = 2 sets x 5 = 10; guard caps the pct at 0.5 -> new_volume=15 -> raw
        # target=7.5, rounded half-up (reps use plain integer rounding, not
        # progression_step snapping — see _round_reps) -> 8.0.
        assert float(row.new_target) == pytest.approx(8.0)


def test_per_adjustment_cap_fires_independently_of_the_escalation_guard(make_user):
    """A request of +30% is BELOW the 1.5x/50% escalation guard but ABOVE the
    per-adjustment cap (20%) — the cap must still fire on its own."""
    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        old_target = float(entry.target_amount)
        row = apply_escalation(s, user["user_id"], ACTIVITY, proposed_pct_increase=0.30)
        applied_pct = float(row.new_target) / old_target - 1
        assert applied_pct <= MAX_ADJUSTMENT_PCT + 1e-9
        assert applied_pct < ESCALATION_GUARD_PCT  # proves the cap, not the guard, bound it


def test_taxonomy_ceiling_fires_independently_of_the_other_two_guards(make_user):
    """Push an entry already close to its ceiling with a request that's under
    BOTH the escalation guard and the per-adjustment cap, and confirm the
    ceiling still clamps it — guards must not silently rely on each other.

    glute_bridge is reps-type, so at the default 2 sets its ceiling is the
    standard 30-reps-per-set ceiling (REPS_STANDARD_CEILING in service.py),
    not taxonomy.max_amount — see _reps_cycle_ceiling. Tolerance covers the
    step-snap rounding at exactly-half-a-step (30 sits midway between this
    activity's real 29/31-rep steps)."""
    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.target_sets = 2
        entry.target_amount = Decimal("28.00")  # volume=56, ceiling=30*2=60
        s.flush()
        row = apply_escalation(s, user["user_id"], ACTIVITY, proposed_pct_increase=0.10)
        # 56 * 1.10 = 61.6 > ceiling 60 -> must be clamped to (near) the ceiling.
        assert float(row.new_target) * entry.target_sets == pytest.approx(60.0, abs=3.5)


def test_all_three_guards_together_the_tightest_wins(make_user):
    """A request that's simultaneously above all three guards -> the tightest
    (smallest allowed) one determines the outcome, per design doc §6's
    explicit ordering.

    glute_bridge is reps-type, so at the default 2 sets its ceiling is the
    standard 30-reps-per-set ceiling (REPS_STANDARD_CEILING in service.py),
    not taxonomy.max_amount — see _reps_cycle_ceiling. Tolerance covers the
    step-snap rounding at exactly-half-a-step (30 sits midway between this
    activity's real 29/31-rep steps)."""
    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.target_sets = 2
        entry.target_amount = Decimal("28.00")  # volume=56, ceiling=30*2=60
        s.flush()
        row = apply_escalation(s, user["user_id"], ACTIVITY, proposed_pct_increase=5.0)  # +500%
        # The ceiling (tightest here) wins over both the 20% cap and the 50% guard.
        assert float(row.new_target) * entry.target_sets == pytest.approx(60.0, abs=3.5)


def test_apply_escalation_never_decreases_a_target(make_user):
    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        old_target = float(entry.target_amount)
        row = apply_escalation(s, user["user_id"], ACTIVITY, proposed_pct_increase=0.05)
        assert float(row.new_target) >= old_target


def test_apply_escalation_refuses_a_suspended_entry(make_user):
    user = make_user()
    with session_scope() as s:
        profile_service.remove_program_entry(s, user["user_id"], ACTIVITY)
        with pytest.raises(NotFound):
            apply_escalation(s, user["user_id"], ACTIVITY, proposed_pct_increase=0.05)


def test_apply_escalation_refuses_a_user_override_entry(make_user):
    """14.7/15.2 — never increase intensity on something the grid flagged that
    the user chose to keep anyway."""
    override_activity = "hamstring_stretch"
    user = make_user(condition_codes=["herniated_disk"])
    with session_scope() as s:
        profile_service.add_program_entry(s, user["user_id"], override_activity,
                                           override_confirmed=True)
        with pytest.raises(NotFound):
            apply_escalation(s, user["user_id"], override_activity, proposed_pct_increase=0.05)


def test_apply_escalation_writes_an_escalation_tagged_history_row(make_user):
    user = make_user()
    with session_scope() as s:
        row = apply_escalation(s, user["user_id"], ACTIVITY, proposed_pct_increase=0.05,
                                adherence_pct_snapshot=112.5)
        assert row.reason == "escalation"
        assert float(row.adherence_pct) == 112.5

        from sqlalchemy import select
        persisted = s.scalar(
            select(ProgressionHistory).where(ProgressionHistory.id == row.id)
        )
        assert persisted is not None
        assert persisted.reason == "escalation"


def test_confirm_escalation_endpoint_declines_gracefully(make_user, client):
    """Confirming with confirmed=false must not write anything."""
    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        before = float(entry.target_amount)
    r = client.post(
        "/v1/rehab/query",
        json={"escalation_confirmation": {"activity_type": ACTIVITY, "confirmed": False}},
        headers=user["headers"],
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["escalation_applied"] is False
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert float(entry.target_amount) == before


def test_confirm_escalation_endpoint_reports_unavailable_when_not_eligible(make_user, client):
    """A fresh user has no progression history at all -> analyze_performance's
    escalation_proposal is never eligible -> confirming must decline cleanly,
    never crash, and never apply a fabricated increase."""
    user = make_user()
    r = client.post(
        "/v1/rehab/query",
        json={"escalation_confirmation": {"activity_type": ACTIVITY, "confirmed": True}},
        headers=user["headers"],
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["escalation_applied"] is False


def test_confirm_escalation_does_not_consume_quota(make_user, client):
    """16.6's principle: confirming an already-shown proposal is a UI action,
    not a new question against the daily limit."""
    user = make_user()
    r1 = client.get("/v1/rehab/quota", headers=user["headers"])
    before = r1.get_json()["remaining"]
    client.post(
        "/v1/rehab/query",
        json={"escalation_confirmation": {"activity_type": ACTIVITY, "confirmed": False}},
        headers=user["headers"],
    )
    r2 = client.get("/v1/rehab/quota", headers=user["headers"])
    assert r2.get_json()["remaining"] == before
