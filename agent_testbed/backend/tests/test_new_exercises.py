"""Exercises added from our own CSV (2026-10-28, hypertension research):
their steps come from data/activity_taxonomy.csv, and they have safety-grid
rows like the original 12 (product team, not clinically reviewed yet)."""
from sqlalchemy import select

from store import plans
from store.models import Condition, Exercise, SafetyRule

NORMAL_BP = {"sys": 125.0, "dia": 80.0, "date": "2026-10-20"}  # below every reading rule
NEW = ["wall_sit", "sit_to_stand", "wall_pushup", "march_in_place", "slow_breathing"]


def test_new_exercises_load_with_their_steps(db):
    for kind in NEW:
        ex = db.get(Exercise, kind)
        assert ex is not None and len(ex.instructions) >= 4, kind
        assert 1 <= ex.default_sets <= ex.max_sets and 0 < ex.default_amount <= ex.max_amount


def test_new_exercises_have_a_verdict_for_every_supported_condition(db):
    supported = set(db.scalars(select(Condition.code).where(Condition.bucket == "supported")))
    for kind in NEW:
        ruled = set(db.scalars(select(SafetyRule.condition_code).where(SafetyRule.activity_type == kind)))
        assert ruled == supported, kind


def test_bp_patients_get_the_new_exercises_with_the_breathing_note(db):
    allowed, _ = plans.candidates(db, ["bp_controlled"], age=50, bmi=24, bp=NORMAL_BP)
    by_type = {c["activity_type"]: c for c in allowed}
    assert set(NEW) <= set(by_type)
    assert by_type["wall_sit"]["verdict"] == "modify" and "hold your breath" in by_type["wall_sit"]["notes"]


def test_knee_pain_keeps_the_wall_sit_shallow(db):
    catalog = {e["activity_type"]: e for e in plans.exercise_catalog(db, ["arthritis_knee"])}
    assert catalog["wall_sit"]["verdict"] == "modify" and "shallow" in catalog["wall_sit"]["notes"]
    assert catalog["sit_to_stand"]["verdict"] == "modify"


def test_new_exercises_rank_after_the_original_twelve(db):
    """Adding them doesn't reorder drafts for other conditions (BP was
    re-ranked on purpose, below)."""
    for r in db.scalars(select(SafetyRule).where(SafetyRule.activity_type.in_(NEW),
                                                 SafetyRule.condition_code != "bp_controlled")):
        assert r.usefulness_rank >= 13, (r.condition_code, r.activity_type)


def test_bp_list_puts_the_research_backed_exercises_first(db):
    allowed, _ = plans.candidates(db, ["bp_controlled"], age=50, bmi=24, bp=NORMAL_BP)
    assert [c["activity_type"] for c in allowed][:5] == [
        "walk", "march_in_place", "sit_to_stand", "slow_breathing", "wall_pushup"]


def test_bp_breath_holding_exercises_carry_the_breathing_note(db):
    allowed, _ = plans.candidates(db, ["bp_controlled"], age=50, bmi=24, bp=NORMAL_BP)
    by_type = {c["activity_type"]: c for c in allowed}
    for kind in ("neck_isometric", "glute_bridge", "dead_bug", "wall_sit"):
        assert by_type[kind]["verdict"] == "modify" and "hold your breath" in by_type[kind]["notes"], kind
    # Other conditions keep them "safe".
    knee = {c["activity_type"]: c for c in plans.candidates(db, ["arthritis_knee"], age=50, bmi=24)[0]}
    assert knee["neck_isometric"]["verdict"] == "safe"


def test_doctor_can_add_a_new_exercise(db):
    chosen = plans.doctor_exercises(db, [{"activity_type": "slow_breathing", "sets": 1, "amount": 10}])
    assert chosen[0]["unit"] == "min" and chosen[0]["amount"] == 10
