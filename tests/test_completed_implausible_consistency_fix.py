"""Regression test for a found-live bug: suggestions_today()'s "completed
today" check didn't exclude flagged-implausible logs, unlike every sibling
date-aggregation function in app/profile/service.py (streak, trend,
activity_log_detail). A single implausible log (e.g. a 20km walk against a
15km plausible_max_total) could mark today's goal "completed": true while
streak() correctly ignored the same log and reported current: 0 — two parts
of the same API surface contradicting each other. Fixed by adding the same
ActivityLog.implausible.is_(False) filter already used everywhere else.

Note: an implausible distance/duration log that also ranks as a personal best
(see PersonalBest / ActivityLog.extraordinary, tests/test_personal_bests.py)
is a deliberate LATER exception to this — it's meant to count. This test pre-
fills the top 5 so the log under test does NOT qualify as extraordinary,
isolating the plain "implausible, not extraordinary" case the original fix
is about.
"""
from app.platform.db import session_scope
from app.profile import service
from app.profile.models import PersonalBest


def test_implausible_log_does_not_mark_todays_goal_completed(make_user):
    user = make_user(condition_codes=["none"])
    with session_scope() as s:
        service.add_program_entry(s, user["user_id"], "walk")

    with session_scope() as s:
        for v in (16, 17, 18, 19, 20):
            s.add(PersonalBest(user_id=user["user_id"], activity_type="walk", value=v, unit="km"))

    with session_scope() as s:
        # walk's plausible_max_total is 15 (data/activity_taxonomy.csv) —
        # 15.5 is flagged implausible but still accepted and stored (4.6);
        # with the top 5 already at 16-20, it doesn't rank as extraordinary.
        result = service.log_activity(s, user["user_id"], activity_type="walk", amount=15.5, sets=1)
        assert result["implausible"] is True
        assert result["extraordinary"] is False

        suggestions = service.suggestions_today(s, user["user_id"])
        walk_item = next(i for i in suggestions["all_items"] if i["activity_type"] == "walk")
        assert walk_item["completed"] is False

        streak = service.streak(s, user["user_id"])
        assert streak["current"] == 0
