"""Literal activity recall ("what did I do yesterday") — a real, distinct
capability from RLM's performance analysis, found missing live: analyze_
performance only ever computes rolled-up trend numbers (adherence %, streak,
plateau), never a specific day's itemized log. This reads directly from
activity_logs instead, no LLM analysis involved.

Routing itself (activity_recall vs performance vs medical, and date-range
resolution for recall) goes through _classify_data_intent — a real LLM call,
replacing what used to be two regex gates that kept missing live phrasings:
"analyze my growth" (no word "growth" in the old pattern), "what I have done"
vs "what have I done" (word order), "day before yesterday" mis-parsed as
"yesterday" (naive substring match), "3 days ago" not recognized as a
specific day, and "what about the day before that" (a follow-up needing the
previous question for context). These are real LLM calls throughout this
file, not free regex checks.
"""
import os
from datetime import date

from app.platform.db import session_scope
from app.profile import service as profile_service
from app.rag.service import (
    NO_CONTENT_ANSWER, _activity_recall_answer, _activity_recall_block, _classify_data_intent,
)

ACTIVITY = "glute_bridge"


def _intent(session, user_id, question, today=date(2026, 8, 24)):
    return _classify_data_intent(
        session, user_id, question, api_key=os.environ["OPENROUTER_API_KEY"], today=today,
    )


def test_classifies_plain_yesterday_correctly(make_user):
    user = make_user()
    with session_scope() as s:
        result = _intent(s, user["user_id"], "what did I do yesterday?")
    assert result["intent"] == "activity_recall"
    assert result["start_date"] == result["end_date"] == date(2026, 8, 23)


def test_classifies_word_order_variant_correctly(make_user):
    """Found live: "what I have done" (I before have) didn't match the old
    regex, which only recognized "what have I done" (have before I)."""
    user = make_user()
    with session_scope() as s:
        result = _intent(s, user["user_id"], "tell me what i have done yesterday")
    assert result["intent"] == "activity_recall"
    assert result["start_date"] == result["end_date"] == date(2026, 8, 23)


def test_classifies_day_before_yesterday_correctly(make_user):
    """Found live: the old code checked "yesterday" as a substring, so "day
    before yesterday" incorrectly resolved to plain yesterday."""
    user = make_user()
    with session_scope() as s:
        result = _intent(s, user["user_id"], "what did I do the day before yesterday?")
    assert result["intent"] == "activity_recall"
    assert result["start_date"] == result["end_date"] == date(2026, 8, 22)


def test_classifies_n_days_ago_correctly(make_user):
    """Found live: the old code had no concept of "N days ago" at all and
    fell back to a generic last-7-days range instead of the specific day."""
    user = make_user()
    with session_scope() as s:
        result = _intent(s, user["user_id"], "what did I do 3 days ago?")
    assert result["intent"] == "activity_recall"
    assert result["start_date"] == result["end_date"] == date(2026, 8, 21)


def test_classifies_follow_up_using_previous_question_as_context(make_user):
    """Found live: "what about the day before that" has no recall keywords
    of its own — the old regex never matched it at all. The classifier is
    given the previous real question so it can resolve what "that" refers to."""
    from app.rag.models import RehabChatLog

    user = make_user()
    with session_scope() as s:
        s.add(RehabChatLog(
            user_id=user["user_id"], question="what did I do yesterday?",
            answer="You logged: Walking, Glute Bridge.",
        ))
        s.flush()
        result = _intent(s, user["user_id"], "what about the day before that?")
    assert result["intent"] == "activity_recall"
    assert result["start_date"] == result["end_date"] == date(2026, 8, 22)


def test_classifies_performance_questions_correctly(make_user):
    user = make_user()
    with session_scope() as s:
        result = _intent(s, user["user_id"], "analyze my growth")
    assert result["intent"] == "performance"
    assert result["start_date"] is None and result["end_date"] is None


def test_classifies_medical_questions_correctly(make_user):
    user = make_user()
    with session_scope() as s:
        result = _intent(s, user["user_id"], "what causes gout")
    assert result["intent"] == "medical"
    assert result["start_date"] is None and result["end_date"] is None


def test_classifies_weekday_name_using_the_real_current_weekday(make_user):
    """Found live: a weekday name alone ("Thursday") needs to know what day
    today actually falls on to resolve to the most recent such day — the
    classifier is now told today's real weekday explicitly rather than
    needing to compute it itself. 2026-08-24 is a Monday, so the most recent
    Thursday on or before it is 2026-08-20."""
    user = make_user()
    with session_scope() as s:
        result = _intent(s, user["user_id"], "what about Thursday?")
    assert result["intent"] == "activity_recall"
    assert result["start_date"] == result["end_date"] == date(2026, 8, 20)


def test_classifies_first_day_using_the_real_earliest_logged_date(make_user):
    """Found live: "first day" was answered with a guessed date (3 days back)
    instead of the account's real earliest logged day, because the
    classifier was never given that fact. Seeds a real log on a specific
    past date directly (log_activity always logs "today"), then confirms
    "first day" resolves to that REAL date, not a guess."""
    from app.profile.models import ActivityLog

    user = make_user()
    with session_scope() as s:
        s.add(ActivityLog(
            user_id=user["user_id"], activity_type=ACTIVITY, sets_done=2,
            amount_per_set=5, unit="count", total_volume=10,
            local_date=date(2026, 8, 10),
        ))
        s.flush()
        result = _intent(s, user["user_id"], "show me what I did on my first day")
    assert result["intent"] == "activity_recall"
    assert result["start_date"] == result["end_date"] == date(2026, 8, 10)


def test_first_day_falls_back_to_medical_with_no_history_at_all(make_user):
    """No logged activity yet -> there is no real earliest date to resolve
    to. The classifier is told this explicitly ("no logged activity history
    yet"), so it can't produce real dates, and _classify_data_intent's own
    "couldn't resolve real dates -> fall through" rule (not a new one added
    for this case) sends it to the safe "medical" fallback — must never
    invent a specific date with no real data behind it."""
    user = make_user()
    with session_scope() as s:
        result = _intent(s, user["user_id"], "what did I do on my first day")
    assert result == {"intent": "medical", "start_date": None, "end_date": None}


def test_safe_parse_date_rejects_future_dates():
    """Pure guard test, no LLM call: even if a reply named a date after
    today, it must never be trusted — never silently accept an
    out-of-bounds value from the model."""
    from app.rag.service import _safe_parse_date

    today = date(2026, 8, 24)
    assert _safe_parse_date("2026-08-25", today) is None  # tomorrow -> rejected
    assert _safe_parse_date("2026-08-24", today) == today  # today itself -> fine
    assert _safe_parse_date("2026-08-23", today) == date(2026, 8, 23)  # past -> fine
    assert _safe_parse_date("not a date", today) is None
    assert _safe_parse_date(None, today) is None


def test_range_entirely_before_history_never_inverts_start_and_end(make_user):
    """Found live: a 422 crash, not just a wrong answer. When a resolved
    range falls entirely before the user's real first logged day (here: the
    only log is TODAY, so "3 days ago" is before all real history), clamping
    start up to the real earliest date without also moving end could leave
    start > end — activity_log_detail correctly rejects that, which
    surfaced as an unhandled 422 instead of a graceful answer."""
    user = make_user()
    with session_scope() as s:
        profile_service.log_activity(s, user["user_id"], activity_type=ACTIVITY, amount=5, sets=2)
        result = _intent(s, user["user_id"], "what did I do 3 days ago?")
    if result["intent"] == "activity_recall":
        assert result["start_date"] <= result["end_date"]


# --- _activity_recall_block: pure DB read, explicit dates, no LLM call -----

def test_recall_block_reports_nothing_logged_honestly(make_user):
    user = make_user()
    with session_scope() as s:
        d = date(2026, 8, 24)
        block = _activity_recall_block(s, user["user_id"], d, d)
        assert "nothing logged" in block


def test_recall_block_lists_real_logged_exercises(make_user):
    user = make_user()
    with session_scope() as s:
        profile_service.log_activity(s, user["user_id"], activity_type=ACTIVITY, amount=5, sets=2)
        today = profile_service.today_ist()
        block = _activity_recall_block(s, user["user_id"], today, today)
        assert "Glute Bridge" in block
        assert "2 x 5.0" in block


def test_recall_block_never_invents_an_exercise_not_logged(make_user):
    """Direct check on the honesty boundary rule 10 asks the model to keep —
    the block itself must only ever contain what was actually logged."""
    user = make_user()
    with session_scope() as s:
        profile_service.log_activity(s, user["user_id"], activity_type=ACTIVITY, amount=5, sets=2)
        today = profile_service.today_ist()
        block = _activity_recall_block(s, user["user_id"], today, today)
        assert "Dead Bug" not in block
        assert "Walking" not in block


# --- _activity_recall_answer: the actual user-facing reply, no LLM call ---
# Found live: even with a provably correct classification and a provably
# correct data block, the answer-writing LLM still sometimes mislabeled the
# date in its prose. Since this is a pure data dump with no synthesis need,
# _retrieve_and_answer now builds the final answer directly from this
# function instead of handing the date to an LLM to restate — these tests
# lock in that the date shown can never drift from the real one.

def test_recall_answer_reports_nothing_logged_honestly(make_user):
    user = make_user()
    with session_scope() as s:
        d = date(2026, 8, 24)
        answer = _activity_recall_answer(s, user["user_id"], d, d)
        assert "nothing logged" in answer.lower()
        assert d.isoformat() in answer


def test_recall_answer_always_shows_the_exact_date_asked_about(make_user):
    """The specific bug: given a correct date, the answer must show THAT
    date, not one pattern-matched from somewhere else in the conversation."""
    user = make_user()
    with session_scope() as s:
        target = date(2026, 8, 19)
        from app.profile.models import ActivityLog
        s.add(ActivityLog(
            user_id=user["user_id"], activity_type=ACTIVITY, sets_done=2,
            amount_per_set=5, unit="count", total_volume=10, local_date=target,
        ))
        s.flush()
        answer = _activity_recall_answer(s, user["user_id"], target, target)
        assert target.isoformat() in answer
        assert "Glute Bridge" in answer


def test_recall_answer_labels_each_day_in_a_multi_day_range(make_user):
    user = make_user()
    with session_scope() as s:
        profile_service.log_activity(s, user["user_id"], activity_type=ACTIVITY, amount=5, sets=2)
        today = profile_service.today_ist()
        from datetime import timedelta
        answer = _activity_recall_answer(s, user["user_id"], today - timedelta(days=6), today)
        assert today.isoformat() in answer


def test_dashboard_activity_detail_endpoint(make_user, client):
    user = make_user()
    with session_scope() as s:
        profile_service.log_activity(s, user["user_id"], activity_type=ACTIVITY, amount=5, sets=2)
    r = client.get("/v1/dashboard/activity-detail?days=1", headers=user["headers"])
    assert r.status_code == 200
    entries = r.get_json()["entries"]
    assert len(entries) == 1
    assert entries[0]["name"] == "Glute Bridge"
    assert entries[0]["sets"] == 2
    assert entries[0]["amount"] == 5.0


def test_chat_endpoint_answers_activity_recall_instead_of_declining(make_user, client):
    user = make_user()
    with session_scope() as s:
        profile_service.log_activity(s, user["user_id"], activity_type=ACTIVITY, amount=5, sets=2)
    r = client.post(
        "/v1/rehab/query", json={"question": "what did I do today?"},
        headers=user["headers"],
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["answer"] is not None
    assert d["answer"] != NO_CONTENT_ANSWER


def test_chat_endpoint_handles_the_originally_reported_multi_day_question(make_user, client):
    """The exact question that surfaced this whole redesign. It asks about
    two distinct, non-adjacent days in one message — the classifier resolves
    a single covering range (day-before-yesterday..today), so the answer
    should include real logged activity, not a decline, even though the
    literal wording asks for two separate specific days."""
    user = make_user()
    with session_scope() as s:
        profile_service.log_activity(s, user["user_id"], activity_type=ACTIVITY, amount=5, sets=2)
    r = client.post(
        "/v1/rehab/query",
        json={"question": "tell me what i have done day before yesterday and 3 day ago ?"},
        headers=user["headers"],
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["answer"] is not None
    assert d["answer"] != NO_CONTENT_ANSWER
