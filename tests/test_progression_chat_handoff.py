"""Phase 4 (Implementation_RLM_plan.md) — wiring analyze_performance into
Module 5's chat path. Verifies the handoff actually reaches the prompt, not
just that analyze_performance returns the right dict in isolation (that's
already covered by tests/test_progression_analysis_*.py).
"""
import os

from sqlalchemy import select

from app.platform.db import session_scope
from app.profile import service as profile_service
from app.profile.models import UserProgram
from app.rag.service import (
    NO_CONTENT_ANSWER, _classify_data_intent, _performance_context,
    _resolve_performance_activity,
)

ACTIVITY = "glute_bridge"


def _suspend_entire_program(session, user_id):
    """Onboarding always auto-creates a full default template program (14.2) —
    there is no real user flow that leaves someone with zero active entries,
    so this directly forces that edge case to test the fallback path."""
    for entry in session.scalars(
        select(UserProgram).where(UserProgram.user_id == user_id)
    ).all():
        entry.status = "suspended"
    session.flush()


# _classify_data_intent replaced the old PERFORMANCE_INTENT_PATTERN /
# ACTIVITY_RECALL_PATTERN regex gates (see the module comment above it in
# app/rag/service.py) — these hit real coverage from real live phrasings a
# fixed keyword list kept missing, so this is a real LLM call per case, not a
# free regex check. Kept intentionally small; the broader intent-routing
# matrix lives in tests/test_activity_recall.py.
def test_classify_intent_recognizes_performance_questions(make_user):
    from datetime import date
    user = make_user()
    for phrase in ["how am I doing", "analyze my growth", "am I getting stronger"]:
        with session_scope() as s:
            result = _classify_data_intent(
                s, user["user_id"], phrase,
                api_key=os.environ["OPENROUTER_API_KEY"], today=date(2026, 8, 24),
            )
        assert result["intent"] == "performance", (phrase, result)


def test_classify_intent_does_not_misroute_ordinary_medical_questions(make_user):
    from datetime import date
    user = make_user()
    for phrase in ["what causes gout", "what is bursitis"]:
        with session_scope() as s:
            result = _classify_data_intent(
                s, user["user_id"], phrase,
                api_key=os.environ["OPENROUTER_API_KEY"], today=date(2026, 8, 24),
            )
        assert result["intent"] == "medical", (phrase, result)


def test_resolve_activity_prefers_a_named_match_over_recency(make_user):
    user = make_user()
    with session_scope() as s:
        profile_service.add_program_entry(s, user["user_id"], ACTIVITY)
        profile_service.add_program_entry(s, user["user_id"], "dead_bug")
        # dead_bug logged most recently, but the question names glute bridges.
        profile_service.log_activity(s, user["user_id"], activity_type="dead_bug",
                                      amount=4, sets=2)
        resolved = _resolve_performance_activity(s, user["user_id"], "how's my glute bridge going")
        assert resolved == ACTIVITY


def test_resolve_activity_falls_back_to_most_recently_logged(make_user):
    user = make_user()
    with session_scope() as s:
        profile_service.add_program_entry(s, user["user_id"], ACTIVITY)
        profile_service.add_program_entry(s, user["user_id"], "dead_bug")
        profile_service.log_activity(s, user["user_id"], activity_type="dead_bug",
                                      amount=4, sets=2)
        resolved = _resolve_performance_activity(s, user["user_id"], "how am I doing overall")
        assert resolved == "dead_bug"


def test_resolve_activity_is_none_with_no_active_program(make_user):
    user = make_user()
    with session_scope() as s:
        _suspend_entire_program(s, user["user_id"])
        resolved = _resolve_performance_activity(s, user["user_id"], "how am I doing")
        assert resolved is None


def test_performance_block_carries_real_tracked_data_into_the_prompt(make_user):
    """The concrete proof the handoff works: the streak value inside the block
    string is the SAME streak this user actually has, computed by the same
    module-4.2 streak() the dashboard uses — not a placeholder."""
    user = make_user()
    with session_scope() as s:
        profile_service.add_program_entry(s, user["user_id"], ACTIVITY)
        profile_service.log_activity(s, user["user_id"], activity_type=ACTIVITY,
                                      amount=5, sets=2)
        block, _confirmation = _performance_context(
            s, user["user_id"], "how am I doing with my glute bridges?",
            openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
        )
        assert block is not None
        assert "Glute Bridge" in block
        assert '"check": "streak"' in block
        assert '"current": 1' in block


def test_chat_endpoint_answers_a_performance_question_instead_of_declining(make_user, client):
    user = make_user()
    with session_scope() as s:
        profile_service.add_program_entry(s, user["user_id"], ACTIVITY)
        profile_service.log_activity(s, user["user_id"], activity_type=ACTIVITY,
                                      amount=5, sets=2)
    r = client.post(
        "/v1/rehab/query", json={"question": "how am I doing with my glute bridges?"},
        headers=user["headers"],
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["answer"] is not None
    assert d["answer"] != NO_CONTENT_ANSWER


def test_performance_question_with_no_program_falls_through_without_crashing(make_user, client):
    """No active program entry to analyze -> the normal medical-only path runs
    unchanged (NO_CONTENT_ANSWER for a question the medical RAG has nothing
    for), not an error."""
    user = make_user()
    with session_scope() as s:
        _suspend_entire_program(s, user["user_id"])
    r = client.post(
        "/v1/rehab/query", json={"question": "how am I doing overall?"},
        headers=user["headers"],
    )
    assert r.status_code == 200
    assert r.get_json()["answer"] is not None  # a real reply either way, never a crash
