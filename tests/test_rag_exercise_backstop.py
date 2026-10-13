"""Regression tests for the third-pass code audit's HIGH finding #4: nothing
enforced prompt rule 1 (only ever name an APPROVED exercise) the way
_enforce_no_medication_or_surgery already enforces rules 2-3. These are pure
unit tests against _enforce_approved_exercises_only directly — no LLM call,
no HTTP round trip — since the function itself takes the model's answer text
as a plain argument.
"""
from app.platform.db import session_scope
from app.rag.service import NO_APPROVED_EXERCISE_ANSWER, _enforce_approved_exercises_only

APPROVED = ["Ankle Circles", "Neck Hold", "Seated Hamstring Stretch"]


def test_leaves_a_clean_answer_untouched(app):
    with session_scope() as s:
        answer, was_corrected = _enforce_approved_exercises_only(
            s, "Try some Ankle Circles a few times a day to stay mobile.", APPROVED,
        )
    assert answer == "Try some Ankle Circles a few times a day to stay mobile."
    assert was_corrected is False


def test_leaves_an_answer_with_no_exercise_names_at_all_untouched(app):
    with session_scope() as s:
        answer, was_corrected = _enforce_approved_exercises_only(
            s, "Rest and apply ice to the area for now.", APPROVED,
        )
    assert answer == "Rest and apply ice to the area for now."
    assert was_corrected is False


def test_blocks_and_offers_the_approved_list_instead_of_an_unapproved_exercise(app):
    original = "You could try some gentle Running to stay active."
    with session_scope() as s:
        answer, was_corrected = _enforce_approved_exercises_only(s, original, APPROVED)
    assert answer != original  # the original recommendation sentence is gone
    assert was_corrected is True  # the caller must skip offering a program-update chip
    for name in APPROVED:
        assert name in answer  # the safe alternatives are offered instead


def test_falls_back_to_a_correctly_worded_decline_when_nothing_is_approved_at_all(app):
    """Found live: this used to fall back to SAFETY_FALLBACK_ANSWER, whose
    wording is specifically about medication/surgery — wrong and confusing
    to show someone who asked about exercise and never mentioned either."""
    with session_scope() as s:
        answer, was_corrected = _enforce_approved_exercises_only(
            s, "You could try some gentle Running to stay active.", [],
        )
    assert answer == NO_APPROVED_EXERCISE_ANSWER
    assert was_corrected is True
    assert "medication" not in answer.lower()
    assert "surgery" not in answer.lower()
