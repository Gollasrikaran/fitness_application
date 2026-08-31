"""Tests for the "revert what I did previously" chat feature (user-requested
directly): after a sport-suggestion confirmation hides some program entries,
the chatbot should recognize a revert/undo request, look up what actually
got hidden, and offer a one-tap way to bring it back.
"""
from app.platform.db import session_scope
from app.profile import service as profile_service
from app.profile.models import UserProgram
from app.progression.service import apply_escalation
from app.rag import service as rag_service


def test_hidden_by_sport_focus_change_only_reports_that_specific_reason(make_user):
    """A manual removal (a different action, a different reason) must never
    show up as a revert candidate — it has its own recovery path already."""
    user = make_user(condition_codes=["none"])
    with session_scope() as s:
        profile_service.set_program_to_activities(s, user["user_id"], ["walk"])  # hides the rest
    with session_scope() as s:
        profile_service.remove_program_entry(s, user["user_id"], "walk")  # manual removal

    with session_scope() as s:
        candidates = rag_service._hidden_by_sport_focus_change(s, user["user_id"])
    types = {c["activity_type"] for c in candidates}
    assert "walk" not in types  # user_removed, not a revert candidate
    assert "glute_bridge" in types  # sport_focus_change, IS a revert candidate


def test_no_candidates_when_nothing_has_been_sport_focus_hidden(make_user):
    user = make_user(condition_codes=["none"])
    with session_scope() as s:
        candidates = rag_service._hidden_by_sport_focus_change(s, user["user_id"])
    assert candidates == []


def test_confirm_revert_restores_with_original_progress_intact(make_user):
    user = make_user(condition_codes=["none"])
    with session_scope() as s:
        apply_escalation(s, user["user_id"], "glute_bridge", 5.0)
        progressed_amount = s.get(UserProgram, (user["user_id"], "glute_bridge")).target_amount

    with session_scope() as s:
        profile_service.set_program_to_activities(s, user["user_id"], ["walk"])
        entry = s.get(UserProgram, (user["user_id"], "glute_bridge"))
        assert entry.status == "suspended"

    with session_scope() as s:
        candidates = rag_service._hidden_by_sport_focus_change(s, user["user_id"])
        types = [c["activity_type"] for c in candidates]
        result = rag_service._confirm_revert(
            s, user["user_id"], {"activity_types": types, "confirmed": True},
        )
    assert result["program_updated"] is True
    assert "Glute Bridge" in result["message"]

    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], "glute_bridge"))
        assert entry.status == "active"
        assert entry.target_amount == progressed_amount  # not reset


def test_confirm_revert_ignores_activity_types_not_actually_hidden(make_user):
    """16.3's principle: re-verify against what's ACTUALLY currently hidden,
    never trust a client-supplied list at face value — an already-active
    exercise (or one hidden for a totally different reason) must not be
    silently "restored" by a stale or crafted request."""
    user = make_user(condition_codes=["none"])
    with session_scope() as s:
        result = rag_service._confirm_revert(
            s, user["user_id"], {"activity_types": ["walk", "running"], "confirmed": True},
        )
    assert result["program_updated"] is False
    assert "Nothing to revert" in result["message"]


def test_declining_a_revert_makes_no_changes(make_user):
    user = make_user(condition_codes=["none"])
    with session_scope() as s:
        profile_service.set_program_to_activities(s, user["user_id"], ["walk"])

    with session_scope() as s:
        result = rag_service._confirm_revert(
            s, user["user_id"], {"activity_types": ["glute_bridge"], "confirmed": False},
        )
    assert result["program_updated"] is False

    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], "glute_bridge"))
        assert entry.status == "suspended"  # unchanged, still hidden


def test_chat_recognizes_a_revert_request_and_offers_the_right_candidates(make_user, client):
    """Live, real-API check: after a sport-focus change, asking the chatbot
    directly to revert must be classified correctly (not answered as a
    medical question) and must offer exactly what was actually hidden."""
    user = make_user(condition_codes=["none"])
    with session_scope() as s:
        profile_service.set_program_to_activities(s, user["user_id"], ["walk", "running"])

    r = client.post(
        "/v1/rehab/query",
        json={"question": "revert what I did previously, bring back my old exercises"},
        headers=user["headers"],
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["needs_revert_confirmation"] is True
    assert d["revert_candidates"]
    candidate_types = {c["activity_type"] for c in d["revert_candidates"]}
    with session_scope() as s:
        expected = {c["activity_type"] for c in rag_service._hidden_by_sport_focus_change(s, user["user_id"])}
    assert candidate_types == expected
