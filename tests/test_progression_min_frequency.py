"""Minimum-frequency gate on weekly growth (MIN_LOGGED_DAYS_FOR_GROWTH).

Found during planning, not a regression: _window_adherence only ever averages
over days that were actually LOGGED, never counting a missed day as a zero —
so a single very strong day, with zero other activity all week, used to
average to that one day's ratio alone, comfortably clearing the 80% grow
threshold on its own. This gates "curve" specifically on having shown it on
enough real days — strong performance on too few days falls through to
"hold", never "reduce".

glute_bridge fixture: default 2x5 (target_volume=10), per data/activity_taxonomy.csv.
"""
from datetime import datetime, timedelta, timezone

from app.platform.db import session_scope
from app.profile.models import ActivityLog, UserProgram
from app.progression.service import MIN_LOGGED_DAYS_FOR_GROWTH, run_weekly_progression

ACTIVITY = "glute_bridge"


def _backdate(session, user_id, weeks, activity_type=ACTIVITY):
    entry = session.get(UserProgram, (user_id, activity_type))
    entry.added_at = datetime.now(timezone.utc) - timedelta(days=weeks * 7 + 1)
    session.flush()


def _seed_days(session, user_id, activity_type, *, sets, amount, today, days):
    """One strong log per day, on `days` distinct days within the trailing window."""
    for i in range(days):
        session.add(ActivityLog(
            user_id=user_id, activity_type=activity_type, sets_done=sets,
            amount_per_set=amount, unit="count", total_volume=sets * amount,
            local_date=today - timedelta(days=i),
        ))


def _row_for(rows, activity_type):
    matches = [r for r in rows if r.activity_type == activity_type]
    assert len(matches) == 1
    return matches[0]


def test_one_strong_day_alone_holds_instead_of_growing(make_user):
    """The exact bug found: one great day, nothing else logged all week, used
    to be enough on its own to trigger growth."""
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        _backdate(s, user["user_id"], weeks=1)
        # One day, well above target (2x5=10) -> >=80% ratio on its own.
        _seed_days(s, user["user_id"], ACTIVITY, sets=2, amount=6, today=today, days=1)
        rows = run_weekly_progression(s, user["user_id"], today=today)
        row = _row_for(rows, ACTIVITY)
        assert row.reason == "hold"
        assert float(row.new_target) == float(row.old_target)


def test_strong_performance_on_enough_days_grows_normally(make_user):
    """Same per-day strength, but shown on MIN_LOGGED_DAYS_FOR_GROWTH distinct
    days -> grows, confirming the gate doesn't block real sustained adherence."""
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        _backdate(s, user["user_id"], weeks=1)
        _seed_days(s, user["user_id"], ACTIVITY, sets=2, amount=6, today=today,
                   days=MIN_LOGGED_DAYS_FOR_GROWTH)
        rows = run_weekly_progression(s, user["user_id"], today=today)
        row = _row_for(rows, ACTIVITY)
        assert row.reason == "curve"
        assert float(row.new_target) > float(row.old_target)


def test_low_adherence_still_reduces_regardless_of_day_count(make_user):
    """The frequency gate must only ever affect the grow path — a genuinely
    poor ratio never grows, even logged on plenty of days. (Not asserting the
    "reduce" label specifically: glute_bridge's progression step is coarse
    enough that a 10% reduction can round right back to the same displayed
    number, which the engine correctly reports as "hold" rather than a
    misleading "reduce" — see test_progression_engine.py's own documented
    caveat about this exact activity for the curve path. The real invariant
    here is "never curve", not the cosmetic reduce-vs-hold label.)"""
    from app.profile.service import today_ist

    user = make_user()
    today = today_ist()
    with session_scope() as s:
        _backdate(s, user["user_id"], weeks=1)
        # 5 days logged, but each well under half the target (2x5=10) -> reduce.
        _seed_days(s, user["user_id"], ACTIVITY, sets=1, amount=2, today=today, days=5)
        rows = run_weekly_progression(s, user["user_id"], today=today)
        row = _row_for(rows, ACTIVITY)
        assert row.reason != "curve"
        assert float(row.new_target) <= float(row.old_target)
