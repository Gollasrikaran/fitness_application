"""Per-set independent progression: opt-in via real per-set logging, the
exact cascade trigger sequence (confirmed, by set number), the continuous
adherence-based drop formula, and Pro level. See PER_SET_PROGRESSION_PLAN.md.

glute_bridge fixture throughout: default 2x5, reps-type, not per-side.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.platform.db import session_scope
from app.profile.models import ActivityLog, UserProgram
from app.progression.models import ProgressionHistory
from app.progression.service import (
    REPS_HARD_CEILING,
    REPS_MAX_SETS,
    REPS_STANDARD_CEILING,
    SET_DROP_MAX_PCT,
    SET_DROP_MIN_PCT,
    _set_drop_pct,
    run_weekly_progression,
    start_per_set_tracking_if_needed,
)

ACTIVITY = "glute_bridge"


def _backdate(session, user_id, weeks, activity_type=ACTIVITY):
    entry = session.get(UserProgram, (user_id, activity_type))
    entry.added_at = datetime.now(timezone.utc) - timedelta(days=weeks * 7 + 1)
    session.flush()


def _seed_set_amounts(session, user_id, activity_type, set_amounts, *, today, days):
    """One log per day carrying a full per-set breakdown, on `days` distinct
    recent dates — real per-set data for the trailing-average/adherence math."""
    total = sum(set_amounts)
    for i in range(days):
        session.add(ActivityLog(
            user_id=user_id, activity_type=activity_type, sets_done=len(set_amounts),
            amount_per_set=total / len(set_amounts), unit="count", total_volume=total,
            set_amounts=[Decimal(str(v)) for v in set_amounts],
            local_date=today - timedelta(days=i),
        ))


def _rows_for(rows, set_number):
    return [r for r in rows if r.set_number == set_number]


# --- opt-in ------------------------------------------------------------

def test_starting_tracking_seeds_every_current_set_at_the_blended_target(make_user):
    user = make_user()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert float(entry.reps_ceiling) == REPS_STANDARD_CEILING
        assert [float(v) for v in entry.set_targets] == [5.0, 5.0]  # default 2x5
        assert [float(v) for v in entry.internal_set_targets] == [5.0, 5.0]


def test_starting_tracking_twice_is_a_no_op(make_user):
    user = make_user()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.set_targets = [Decimal("20.00"), Decimal("10.00")]  # pretend real divergence happened
        s.flush()
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)  # must not reset it
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert [float(v) for v in entry.set_targets] == [20.0, 10.0]


def test_non_reps_activity_never_starts_per_set_tracking(make_user):
    user = make_user()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], "walk")  # distance-type
        entry = s.get(UserProgram, (user["user_id"], "walk"))
        assert entry.reps_ceiling is None


def test_logging_set_amounts_via_the_route_starts_tracking(make_user, client):
    user = make_user()
    r = client.post(
        "/v1/activities",
        json={"activity_type": ACTIVITY, "set_amounts": [10, 8]},
        headers=user["headers"],
    )
    assert r.status_code == 201
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert entry.reps_ceiling is not None


def test_old_system_entries_are_completely_unaffected(make_user):
    """An entry that never logs set_amounts must never be touched by any of
    this — same single-blended-target behavior as before this feature."""
    user = make_user()
    with session_scope() as s:
        _backdate(s, user["user_id"], weeks=1)
        s.add(ActivityLog(
            user_id=user["user_id"], activity_type=ACTIVITY, sets_done=2,
            amount_per_set=8, unit="count", total_volume=16,
            local_date=__import__("app.profile.service", fromlist=["today_ist"]).today_ist(),
        ))
        s.flush()
        rows = run_weekly_progression(s, user["user_id"], today=__import__(
            "app.profile.service", fromlist=["today_ist"]).today_ist())
        matches = [r for r in rows if r.activity_type == ACTIVITY]
        assert len(matches) == 1  # the OLD one-row-per-entry shape, not per-set
        assert matches[0].set_number is None
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert entry.reps_ceiling is None
        assert entry.set_targets is None


# --- the continuous drop formula ----------------------------------------

def test_drop_pct_is_minimum_at_full_adherence():
    assert abs(_set_drop_pct(1.0) - SET_DROP_MIN_PCT) < 1e-9


def test_drop_pct_is_maximum_at_floor_adherence():
    assert abs(_set_drop_pct(0.50) - SET_DROP_MAX_PCT) < 1e-9


def test_drop_pct_is_smooth_not_a_cliff():
    """No discrete bucket boundary — two close adherence values must produce
    close drop percentages, not a jump."""
    d_89 = _set_drop_pct(0.89)
    d_91 = _set_drop_pct(0.91)
    assert abs(d_89 - d_91) < 0.02
    midpoint = _set_drop_pct(0.75)
    assert SET_DROP_MIN_PCT < midpoint < SET_DROP_MAX_PCT


def test_drop_pct_clamps_outside_the_defined_range():
    assert abs(_set_drop_pct(2.0) - SET_DROP_MIN_PCT) < 1e-9  # way above ceiling -> still the minimum
    assert abs(_set_drop_pct(0.0) - SET_DROP_MAX_PCT) < 1e-9  # way below floor -> still the maximum


# --- the cascade: Set 1 -> creates Set 3 ---------------------------------

def test_set_1_alone_hitting_ceiling_creates_set_3_not_waiting_for_set_2(make_user):
    """Confirmed precisely: Set 2 does NOT need to also hit ceiling first."""
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        _backdate(s, user["user_id"], weeks=1)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        # Set 1 already at the ceiling, Set 2 comfortably below it.
        entry.set_targets = [Decimal(str(REPS_STANDARD_CEILING)), Decimal("22.00")]
        entry.internal_set_targets = [Decimal(str(REPS_STANDARD_CEILING)), Decimal("22.000000")]
        s.flush()
        # Strong, consistent recent performance on both existing sets so the
        # exercise-wide gate grows this week (adherence record needed).
        _seed_set_amounts(s, user["user_id"], ACTIVITY, [30, 22], today=today, days=5)

        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert entry.target_sets == 3
        targets = [float(v) for v in entry.set_targets]
        assert len(targets) == 3
        # Descending, and Set 3 strictly below Set 2 (the cap rule).
        assert targets[0] >= targets[1] >= targets[2]
        created = [r for r in rows if r.reason == "set_created"]
        assert len(created) == 1
        assert created[0].set_number == 3


def test_set_creation_never_exceeds_the_following_sets_new_value(make_user):
    """The 90%-of-following cap must actually bind when the raw blend would
    otherwise exceed it."""
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        _backdate(s, user["user_id"], weeks=1)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.set_targets = [Decimal(str(REPS_STANDARD_CEILING)), Decimal("29.00")]
        entry.internal_set_targets = [Decimal(str(REPS_STANDARD_CEILING)), Decimal("29.000000")]
        s.flush()
        _seed_set_amounts(s, user["user_id"], ACTIVITY, [30, 29], today=today, days=5)

        run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        targets = [float(v) for v in entry.set_targets]
        assert targets[2] <= round(targets[1] * 0.90) + 1  # allow rounding slack


# --- the cascade: Set 2 -> creates Set 4 ---------------------------------

def test_set_2_hitting_ceiling_with_3_sets_creates_set_4(make_user):
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        _backdate(s, user["user_id"], weeks=1)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.set_targets = [Decimal("24.00"), Decimal(str(REPS_STANDARD_CEILING)), Decimal("15.00")]
        entry.internal_set_targets = [Decimal("24.000000"), Decimal(str(REPS_STANDARD_CEILING)),
                                       Decimal("15.000000")]
        s.flush()
        _seed_set_amounts(s, user["user_id"], ACTIVITY, [24, 30, 15], today=today, days=5)

        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert entry.target_sets == 4
        created = [r for r in rows if r.reason == "set_created"]
        assert len(created) == 1
        assert created[0].set_number == 4


def test_set_3_hitting_ceiling_with_only_3_sets_does_not_trigger_creation(make_user):
    """Only Set 2 hitting ceiling creates Set 4 — Set 3 (the newest, last
    position with only 3 sets) hitting its own ceiling does nothing special
    yet, since the 4-set-max rules don't apply until there ARE 4 sets.

    Set 1/Set 2 are seeded low (well under ~10, the point below which even
    this curve's steep first-touch jump stays under the 30 ceiling) so ONLY
    Set 3 actually crosses this week — isolating the one trigger under test
    from the formula's own aggressive early-stage growth, confirmed against
    the existing reps fast-track this engine reuses unchanged."""
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        _backdate(s, user["user_id"], weeks=1)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.set_targets = [Decimal("9.00"), Decimal("9.00"), Decimal(str(REPS_STANDARD_CEILING))]
        entry.internal_set_targets = [Decimal("9.000000"), Decimal("9.000000"),
                                       Decimal(str(REPS_STANDARD_CEILING))]
        s.flush()
        _seed_set_amounts(s, user["user_id"], ACTIVITY, [9, 9, 30], today=today, days=5)

        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert entry.target_sets == 3  # unchanged
        assert not any(r.reason == "set_created" for r in rows)


# --- the cascade: Set 3 -> boosts Set 4 only (4-set max) ------------------

def test_set_3_hitting_ceiling_at_max_sets_only_boosts_set_4_never_creates_set_5(make_user):
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        _backdate(s, user["user_id"], weeks=1)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.set_targets = [Decimal("27.00"), Decimal("24.00"),
                              Decimal(str(REPS_STANDARD_CEILING)), Decimal("16.00")]
        entry.internal_set_targets = [Decimal("27.000000"), Decimal("24.000000"),
                                       Decimal(str(REPS_STANDARD_CEILING)), Decimal("16.000000")]
        s.flush()
        _seed_set_amounts(s, user["user_id"], ACTIVITY, [27, 24, 30, 16], today=today, days=5)

        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert entry.target_sets == REPS_MAX_SETS  # still exactly 4 — never a 5th
        boosts = [r for r in rows if r.reason == "set_boost"]
        assert len(boosts) == 1
        assert boosts[0].set_number == 4
        new_set4 = float(entry.set_targets[3])
        assert new_set4 >= 16.0  # grew (or at minimum held), never dropped
        assert new_set4 <= REPS_STANDARD_CEILING  # still capped at the current ceiling


# --- Pro level: Set 4 hits ceiling -----------------------------------------

def test_set_4_hitting_ceiling_at_max_sets_triggers_pro_level(make_user):
    """Sets 1-3 seeded below the curve's first-touch-jump threshold (~10, see
    the Set-3-isolation test above) so only Set 4 crosses this week — if Set 3
    also crossed, the "boost Set 4" rule would correctly take priority instead
    (confirmed separately), which would mask what this test is checking."""
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        _backdate(s, user["user_id"], weeks=1)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.set_targets = [Decimal("9.00"), Decimal("9.00"), Decimal("9.00"),
                              Decimal(str(REPS_STANDARD_CEILING))]
        entry.internal_set_targets = [Decimal("9.000000"), Decimal("9.000000"),
                                       Decimal("9.000000"), Decimal(str(REPS_STANDARD_CEILING))]
        s.flush()
        _seed_set_amounts(s, user["user_id"], ACTIVITY, [9, 9, 9, 30], today=today, days=5)

        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert float(entry.reps_ceiling) == REPS_HARD_CEILING
        assert entry.pro_leveled_at is not None
        assert entry.target_sets == REPS_MAX_SETS  # still exactly 4, never a 5th
        assert any(r.reason == "pro_level" for r in rows)


def test_pro_level_only_fires_once_not_every_week_at_the_new_ceiling(make_user):
    """Once at REPS_HARD_CEILING, hitting it again must hold, not try to
    level up a second time (no level beyond the two-stage ceiling exists)."""
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        _backdate(s, user["user_id"], weeks=1)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        entry.reps_ceiling = Decimal(str(REPS_HARD_CEILING))
        entry.set_targets = [Decimal("45.00"), Decimal("40.00"), Decimal("35.00"),
                              Decimal(str(REPS_HARD_CEILING))]
        entry.internal_set_targets = [Decimal("45.000000"), Decimal("40.000000"),
                                       Decimal("35.000000"), Decimal(str(REPS_HARD_CEILING))]
        s.flush()
        _seed_set_amounts(s, user["user_id"], ACTIVITY, [45, 40, 35, 50], today=today, days=5)

        rows = run_weekly_progression(s, user["user_id"], today=today)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert float(entry.reps_ceiling) == REPS_HARD_CEILING  # unchanged, no 3rd level
        assert not any(r.reason == "pro_level" for r in rows)


# --- hold/reduce still apply, exercise-wide, before any per-set growth ----

def test_low_adherence_holds_or_reduces_every_set_without_any_cascade(make_user):
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        _backdate(s, user["user_id"], weeks=1)
        # Well under half the blended target (2x5=10) -> reduce, exercise-wide.
        _seed_set_amounts(s, user["user_id"], ACTIVITY, [2, 1], today=today, days=5)

        rows = run_weekly_progression(s, user["user_id"], today=today)
        matches = [r for r in rows if r.activity_type == ACTIVITY]
        assert len(matches) == 2  # one per set, none "set_created"/"set_boost"/"pro_level"
        assert all(r.reason in ("reduce", "hold") for r in matches)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert entry.target_sets == 2  # no cascade fired
