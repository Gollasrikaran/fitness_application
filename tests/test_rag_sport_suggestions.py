"""Regression tests for two related bugs found live (via a real user report,
not the automated audits): a user with NO selected condition ("none" — likely
most beginner users) asked a sport-readiness question ("what exercises help
me start playing football") and got a generic non-answer every time.

Root cause #1: the safety grid had zero "safe" rows for condition_code="none"
(nobody had ever explicitly marked anything safe for "no condition"), so
_approved_activities returned an empty list, and the chatbot's own safety
rule (never name an exercise unless it's on the approved list) correctly, but
uselessly, refused to name anything. Fixed with real data rows (safety_grid.
csv), not a code change to the safety rule itself — the rule was working
correctly, the underlying data was just missing for this one condition.

Root cause #2: even with the approved list populated, the model had no
signal connecting "this sport's demands" to "which approved exercise
actually helps" — it just repeated the whole approved list with generic
filler ("these can support the quick movements..."). Fixed by annotating the
approved list with what each exercise actually helps with (ACTIVITY_
CATEGORIES) and instructing the model to reason from that, not just list
everything.

A live LLM call is inherently non-deterministic, so these tests assert the
STRUCTURAL fix (the approved list itself is no longer empty) with certainty,
and assert the OBSERVABLE behavior change (a real exercise gets named, not
the generic fallback) as a live, real-API check.
"""
from app.platform.db import session_scope
from app.rag.service import ACTIVITY_CATEGORIES, NO_APPROVED_EXERCISE_ANSWER, _approved_activities

ALL_CATALOG_DISPLAY_NAMES = {
    "Walking", "Running", "Glute Bridge", "Dead Bug", "Ankle Circles",
    "Wrist Circles", "Shoulder Circles", "Neck Hold", "Seated Hamstring Stretch",
    "Side-Lying Thigh Stretch", "Wall Calf Stretch", "Seated Side Stretch",
}


def test_none_condition_has_a_real_non_empty_approved_list(app):
    """The actual root cause: a user with no selected condition used to have
    ZERO approved exercises, no matter what they asked."""
    with session_scope() as s:
        approved = _approved_activities(s, ["none"])
    assert approved, "condition='none' must have real approved exercises, not an empty list"
    assert set(approved) == ALL_CATALOG_DISPLAY_NAMES


def test_every_catalog_activity_has_a_category_tag():
    """A future new exercise added to the catalog without a matching entry
    here would silently fall back to the generic 'general movement' tag,
    quietly weakening the model's ability to reason about sport-specific fit
    — this keeps the two in sync."""
    missing = ALL_CATALOG_DISPLAY_NAMES - set(ACTIVITY_CATEGORIES)
    assert not missing, f"no category tag for: {missing}"
    for name, category in ACTIVITY_CATEGORIES.items():
        assert isinstance(category, str) and category.strip(), f"empty category for {name!r}"


def test_sport_question_gets_a_real_exercise_not_the_generic_fallback(make_user, client):
    """Live, real-API check of the actual user-facing behavior change. Not
    asserting exactly which exercises get named (that's the model's judgment
    call, and legitimately varies by sport) — just that a user with no
    condition now gets SOME real, approved exercise named, instead of the
    generic 'I don't have a specific exercise...' non-answer this bug used
    to produce every single time."""
    user = make_user(condition_codes=["none"])
    r = client.post(
        "/v1/rehab/query",
        json={"question": "i want to play football, what exercises can help me get started"},
        headers=user["headers"],
    )
    assert r.status_code == 200
    answer = r.get_json()["answer"]
    assert answer != NO_APPROVED_EXERCISE_ANSWER
    assert any(name in answer for name in ALL_CATALOG_DISPLAY_NAMES), (
        f"expected at least one real catalog exercise named in the answer, got: {answer}"
    )
    # The chat UI only renders bold text and bullet lists — a markdown table
    # would show up as broken, literal pipe characters (found live).
    assert "|" not in answer or answer.count("|") < 3, (
        f"answer looks like it contains a markdown table, which the chat UI can't render: {answer}"
    )
