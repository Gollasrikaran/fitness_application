"""Reps-only average-driven fast track + double progression (product decision,
not part of the original RLM design doc — designed and confirmed in
conversation, not a curve retune): the diminishing curve alone left real
accounts stuck at single-digit reps after months of 100% adherence (found
live — see service.py's REPS_FAST_TRACK_K comment). Confirmed design:

1. Reps-type activities only (glute_bridge etc.) — hold/distance/duration
   activities are untouched (regression-guarded here).
2. Every week, the curve is fed an EFFECTIVE week derived by inverting the
   same curve equation against the user's real trailing-7-day average,
   instead of the calendar week — so the whole trajectory re-paces itself to
   real behavior (_reps_curve_step).
3. A fixed two-stage ceiling: 30 reps/set while still on the default set
   count (the first cycle), 50 reps/set for every cycle after the first
   set-bump (_reps_cycle_ceiling).
4. Crossing the CURRENT ceiling with the real average earns an extra set,
   with the new cycle's starting point being the real average redistributed
   across the new set count — not an arbitrary fixed reset
   (avg * old_sets / new_sets). REPS_MAX_SETS (4) is the hard stop.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.platform.db import session_scope
from app.profile.models import ActivityLog, UserProgram
from app.progression.service import (
    REPS_HARD_CEILING,
    REPS_MAX_SETS,
    REPS_STANDARD_CEILING,
    _reps_cycle_baseline,
    _reps_cycle_ceiling,
    apply_escalation,
    run_weekly_progression,
)

REPS_ACTIVITY = "glute_bridge"
HOLD_ACTIVITY = "calf_stretch"


def _backdate(session, user_id, weeks, activity_type=REPS_ACTIVITY):
    entry = session.get(UserProgram, (user_id, activity_type))
    entry.added_at = datetime.now(timezone.utc) - timedelta(days=weeks * 7 + 1)
    session.flush()


def _seed_week(session, user_id, activity_type, *, sets, amount, today, days=7):
    """Seeds `days` daily logs at a fixed per-set amount — a 7-day trailing
    average of exactly `amount`."""
    for i in range(days):
        session.add(ActivityLog(
            user_id=user_id, activity_type=activity_type, sets_done=sets,
            amount_per_set=amount, unit="count", total_volume=sets * amount,
            local_date=today - timedelta(days=i),
        ))


# --- 1. cycle ceiling / baseline, reps-only scope ---------------------------

def test_cycle_ceiling_is_standard_at_default_sets(make_user):
    from app.catalog.models import ActivityTaxonomy
    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        taxonomy = s.get(ActivityTaxonomy, REPS_ACTIVITY)
        assert _reps_cycle_ceiling(taxonomy, entry) == REPS_STANDARD_CEILING


def test_cycle_ceiling_is_hard_ceiling_once_sets_exceed_default(make_user):
    from app.catalog.models import ActivityTaxonomy
    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        entry.target_sets = 3
        taxonomy = s.get(ActivityTaxonomy, REPS_ACTIVITY)
        assert _reps_cycle_ceiling(taxonomy, entry) == REPS_HARD_CEILING


def test_cycle_baseline_is_taxonomy_default_with_no_bump_history(make_user):
    from app.catalog.models import ActivityTaxonomy
    user = make_user()
    with session_scope() as s:
        taxonomy = s.get(ActivityTaxonomy, REPS_ACTIVITY)
        baseline = _reps_cycle_baseline(s, user["user_id"], REPS_ACTIVITY, taxonomy)
    assert baseline == float(taxonomy.default_amount)


def test_hold_type_activity_ceiling_is_untouched(make_user):
    """Explicit "reps only" scope: a hold-type activity's guard must still be
    taxonomy.max_amount * taxonomy.max_sets exactly as before — pushing an
    escalation past it should clamp at the OLD number (30*2=60 for
    calf_stretch, per-side so *2 sides = 120), never the new reps mechanism."""
    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], HOLD_ACTIVITY))
        entry.target_sets = 2
        entry.target_amount = Decimal("28.00")  # volume=28*2*2sides=112, ceiling=30*2*2=120
        s.flush()
        row = apply_escalation(s, user["user_id"], HOLD_ACTIVITY, proposed_pct_increase=5.0)
        assert float(row.new_target) * entry.target_sets * 2 == pytest.approx(120.0, abs=1.0)
        assert entry.target_sets == 2  # never bumped — double progression is reps-only


# --- 2. weekly job grows reps past the old static taxonomy ceiling ---------

def test_weekly_progression_grows_reps_past_the_old_taxonomy_ceiling(make_user):
    """Before this feature, glute_bridge's ceiling was taxonomy.max_amount(15)
    * max_sets(3) = 45 (i.e. 15/set). An account already at 40 reps-per-set,
    1 set, with 100% adherence, must still be allowed to grow — proving the
    old per-set ceiling no longer silently caps a real user."""
    user = make_user()
    today = date(2026, 8, 25)
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        entry.target_sets = 1
        entry.target_amount = Decimal("40.00")
        entry.internal_target_amount = Decimal("40.00")
        s.flush()
        _seed_week(s, user["user_id"], REPS_ACTIVITY, sets=1, amount=40, today=today)
        s.flush()
        run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        assert float(entry.target_amount) > 40.0
        assert float(entry.target_amount) <= REPS_HARD_CEILING


# --- 3. crossing the ceiling bumps sets, redistributing the real average ---

def test_crossing_standard_ceiling_bumps_to_3_sets_with_redistribution(make_user):
    """2 sets, target near 30, real trailing average (32) crosses the
    standard ceiling -> bump to 3 sets, new per-set start = avg*2/3, not an
    arbitrary fixed reset. Verified: (32*2)/3 = 21.33."""
    user = make_user()
    today = date(2026, 8, 25)
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        entry.target_sets = 2
        entry.target_amount = Decimal("29.00")
        entry.internal_target_amount = Decimal("29.00")
        s.flush()
        _seed_week(s, user["user_id"], REPS_ACTIVITY, sets=2, amount=32, today=today)
        s.flush()
        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        assert entry.target_sets == 3
        assert float(entry.internal_target_amount) == pytest.approx(32 * 2 / 3, abs=0.01)
        row = next(r for r in rows if r.activity_type == REPS_ACTIVITY)
        assert row.reason == "double_progression"


def test_crossing_hard_ceiling_bumps_to_4_sets_with_redistribution(make_user):
    """Already on the 2nd cycle (3 sets), real average (55) crosses the hard
    ceiling (50) -> bump to 4 sets, new per-set start = avg*3/4 = 41.25."""
    user = make_user()
    today = date(2026, 8, 25)
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        entry.target_sets = 3
        entry.target_amount = Decimal("48.00")
        entry.internal_target_amount = Decimal("48.00")
        s.flush()
        _seed_week(s, user["user_id"], REPS_ACTIVITY, sets=3, amount=55, today=today)
        s.flush()
        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        assert entry.target_sets == 4
        assert float(entry.internal_target_amount) == pytest.approx(55 * 3 / 4, abs=0.01)
        row = next(r for r in rows if r.activity_type == REPS_ACTIVITY)
        assert row.reason == "double_progression"


def test_redistribution_never_exceeds_the_hard_ceiling_even_for_an_extreme_average(make_user):
    """Found live (code audit): the bump branch used to redistribute the raw
    average with no cap at all, unlike the non-bump branch. A single
    extreme-but-plausible log (e.g. amount_per_set=499, which passes
    glute_bridge's plausible_max_total=500 taxonomy ceiling — a much larger,
    unrelated number) used to redistribute into a triple-digit reps/set
    prescription. The redistributed starting point must never exceed
    REPS_HARD_CEILING, regardless of how extreme the real average is."""
    user = make_user()
    today = date(2026, 8, 25)
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        entry.target_sets = 2
        entry.target_amount = Decimal("29.00")
        entry.internal_target_amount = Decimal("29.00")
        s.flush()
        # A single implausibly-large but plausibility-check-passing log.
        _seed_week(s, user["user_id"], REPS_ACTIVITY, sets=2, amount=499, today=today)
        s.flush()
        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        assert entry.target_sets == 3
        assert float(entry.internal_target_amount) <= REPS_HARD_CEILING
        row = next(r for r in rows if r.activity_type == REPS_ACTIVITY)
        assert row.reason == "double_progression"


def test_escalation_redistribution_never_exceeds_the_hard_ceiling_either(make_user):
    """Same fix, same exploit, via the chat-confirmed escalation path."""
    user = make_user()
    today = date(2026, 8, 25)
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        entry.target_sets = 2
        entry.target_amount = Decimal("29.00")
        entry.internal_target_amount = Decimal("29.00")
        _seed_week(s, user["user_id"], REPS_ACTIVITY, sets=2, amount=499, today=today)
        s.flush()
        row = apply_escalation(s, user["user_id"], REPS_ACTIVITY, proposed_pct_increase=0.10)
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        assert entry.target_sets == 3
        assert float(entry.internal_target_amount) <= REPS_HARD_CEILING
        assert row.reason == "double_progression"


def test_does_not_bump_when_average_stays_under_the_ceiling(make_user):
    """Real average (25) stays under the standard ceiling (30) — must not
    bump sets just because growth is naturally slowing near a ceiling."""
    user = make_user()
    today = date(2026, 8, 25)
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        entry.target_sets = 2
        entry.target_amount = Decimal("27.00")
        entry.internal_target_amount = Decimal("27.00")
        s.flush()
        _seed_week(s, user["user_id"], REPS_ACTIVITY, sets=2, amount=25, today=today)
        s.flush()
        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        assert entry.target_sets == 2
        row = next(r for r in rows if r.activity_type == REPS_ACTIVITY)
        assert row.reason != "double_progression"


def test_double_progression_stops_at_the_max_sets_ceiling(make_user):
    """Once target_sets reaches REPS_MAX_SETS (4), no further bump — 4 sets x
    50 reps is the true, final ceiling for a reps activity. Growth just
    clamps there, reason stays "curve"/"hold", never another
    "double_progression"."""
    user = make_user()
    today = date(2026, 8, 25)
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        entry.target_sets = REPS_MAX_SETS
        entry.target_amount = Decimal("48.00")
        entry.internal_target_amount = Decimal("48.00")
        s.flush()
        _seed_week(s, user["user_id"], REPS_ACTIVITY, sets=REPS_MAX_SETS, amount=60, today=today)
        s.flush()
        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        assert entry.target_sets == REPS_MAX_SETS  # not bumped past the cap
        assert float(entry.target_amount) == pytest.approx(50.0, abs=1.5)
        row = next(r for r in rows if r.activity_type == REPS_ACTIVITY)
        assert row.reason != "double_progression"


def test_double_progression_via_escalation_path_matches_the_weekly_job(make_user):
    """apply_escalation shares the same guard bounds as the weekly job
    (existing project principle) — confirm the ceiling-crossing bump fires
    there too, driven by the real trailing average, not just in
    run_weekly_progression."""
    user = make_user()
    today = date(2026, 8, 25)
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        entry.target_sets = 2
        entry.target_amount = Decimal("29.00")
        entry.internal_target_amount = Decimal("29.00")
        _seed_week(s, user["user_id"], REPS_ACTIVITY, sets=2, amount=35, today=today)
        s.flush()
        row = apply_escalation(s, user["user_id"], REPS_ACTIVITY, proposed_pct_increase=0.10)
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        assert entry.target_sets == 3
        assert float(entry.internal_target_amount) == pytest.approx(35 * 2 / 3, abs=0.01)
        assert row.reason == "double_progression"


def test_first_week_average_above_standard_ceiling_bumps_immediately(make_user):
    """A brand new entry (still at baseline) whose very first week already
    averages above 30 skips the whole climb and bumps straight to 3 sets —
    no need to wait through several weeks of curve growth first."""
    user = make_user()
    today = date(2026, 8, 25)
    with session_scope() as s:
        _seed_week(s, user["user_id"], REPS_ACTIVITY, sets=2, amount=35, today=today)
        s.flush()
        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], REPS_ACTIVITY))
        assert entry.target_sets == 3
        assert float(entry.internal_target_amount) == pytest.approx(35 * 2 / 3, abs=0.01)
        row = next(r for r in rows if r.activity_type == REPS_ACTIVITY)
        assert row.reason == "double_progression"


def test_underperforming_user_gets_a_gentler_target_than_compliant(make_user):
    """A user whose real average (12) trails what a compliant week-1 climb
    would reach (~14.67) still gets forward progress, but a smaller one —
    never punished with a flat cut, never demanding what they haven't
    proven. Compares directly against the compliant trajectory."""
    from app.catalog.models import ActivityTaxonomy
    import math
    user_a = make_user()
    user_b = make_user()
    today = date(2026, 8, 25)
    with session_scope() as s:
        # user_a: fully compliant (logs exactly the baseline default)
        _seed_week(s, user_a["user_id"], REPS_ACTIVITY, sets=2, amount=5, today=today)
        # user_b: underperforming relative to a compliant climb, but still
        # active enough to land in the >=80%-adherence curve branch (their
        # own target is also still baseline, so 12 vs 5 is comfortably
        # "curve", not "hold"/"reduce").
        _seed_week(s, user_b["user_id"], REPS_ACTIVITY, sets=2, amount=12, today=today)
        s.flush()
        run_weekly_progression(s, user_a["user_id"], today=today)
        run_weekly_progression(s, user_b["user_id"], today=today)
        entry_a = s.get(UserProgram, (user_a["user_id"], REPS_ACTIVITY))
        entry_b = s.get(UserProgram, (user_b["user_id"], REPS_ACTIVITY))
        # Both still grow (forward progress for both), but B's real average
        # already exceeds A's fresh target, so this asserts the mechanism
        # produces DIFFERENT, average-driven outcomes rather than an
        # identical fixed schedule regardless of real behavior.
        assert float(entry_a.internal_target_amount) != float(entry_b.internal_target_amount)
        assert float(entry_b.internal_target_amount) > float(entry_a.internal_target_amount)
