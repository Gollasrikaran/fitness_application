"""Exercises added 2026-10-29 (diabetes research, library review): balance,
knee, neck and chair exercises. Steps come from data/activity_taxonomy.csv;
grid rows are product team, not clinically reviewed yet."""
from sqlalchemy import select

from store import plans
from store.models import Condition, Exercise, SafetyRule
from store.seed import EXERCISE_PROPERTIES

NEW = ["calf_raise", "seated_knee_extension", "single_leg_stand", "heel_toe_walk", "standing_hip_abduction",
       "seated_march", "chair_hamstring_stretch", "chin_tuck"]
DISC = ["herniated_disk", "degenerative_disc", "spinal_stenosis"]
RERANKED = {"bp_controlled", "diabetes_controlled", "prediabetes", "obesity", "arthritis_knee", "arthritis_hip",
            "spondylosis"}
NORMAL = {"bp": {"sys": 125.0, "dia": 80.0, "date": "2026-10-20"}}


def first(db, code, n=5):
    return [c["activity_type"] for c in plans.candidates(db, [code], age=50, bmi=24, readings=NORMAL)[0]][:n]


def test_new_exercises_load_with_their_steps_and_known_properties(db):
    for kind in NEW:
        ex = db.get(Exercise, kind)
        assert ex is not None and len(ex.instructions) >= 3, kind
        assert 1 <= ex.default_sets <= ex.max_sets and 0 < ex.default_amount <= ex.max_amount, kind
        for prop, allowed in EXERCISE_PROPERTIES.items():
            assert getattr(ex, prop) in allowed, (kind, prop)
        assert ex.impact == "low" and ex.intensity == "light" and not ex.breath_hold, kind
        assert ex.position in ("standing", "chair"), kind  # none on the floor


def test_new_exercises_have_a_verdict_for_every_supported_condition_and_no_avoid(db):
    supported = set(db.scalars(select(Condition.code).where(Condition.bucket == "supported")))
    for kind in NEW:
        rules = list(db.scalars(select(SafetyRule).where(SafetyRule.activity_type == kind)))
        assert {r.condition_code for r in rules} == supported, kind
        assert all(r.verdict != "avoid" for r in rules), kind
        assert all(r.usefulness_rank >= 18 for r in rules if r.condition_code not in RERANKED), kind


def test_every_condition_ranks_each_exercise_once(db):
    ranks = {}
    for r in db.scalars(select(SafetyRule)):
        ranks.setdefault(r.condition_code, []).append(r.usefulness_rank)
    for code in RERANKED - {"bp_controlled"}:
        assert sorted(ranks[code]) == list(range(1, 26)), code


def test_reranked_conditions_put_the_research_backed_exercises_first(db):
    assert first(db, "diabetes_controlled") == ["walk", "march_in_place", "sit_to_stand", "calf_raise", "wall_pushup"]
    assert first(db, "prediabetes") == first(db, "diabetes_controlled")
    assert first(db, "obesity", 3) == ["walk", "march_in_place", "seated_march"]
    # "safe" comes before "modify" whatever the rank: the knee straightening (knee), side leg raise (hip) and
    # chin tuck (neck) are "modify" there, so they follow the safe exercises.
    assert first(db, "arthritis_knee", 3) == ["walk", "standing_hip_abduction", "glute_bridge"]
    assert first(db, "arthritis_hip", 2) == ["walk", "seated_knee_extension"]
    assert first(db, "spondylosis", 2) == ["neck_isometric", "shoulder_circles"]


def test_diabetes_breath_holding_exercises_carry_the_breathing_note(db):
    for code in ("diabetes_controlled", "prediabetes"):
        by_type = {c["activity_type"]: c for c in plans.candidates(db, [code], age=50, bmi=24, readings=NORMAL)[0]}
        for kind in ("wall_sit", "neck_isometric", "glute_bridge", "dead_bug"):
            assert by_type[kind]["verdict"] == "modify" and "hold your breath" in by_type[kind]["notes"], (code, kind)
        assert by_type["running"]["verdict"] == "modify", code


def test_walking_is_in_minutes_with_steps(db):
    walk = db.get(Exercise, "walk")
    assert (walk.prescription_type, walk.amount_unit, walk.default_amount, walk.max_amount) == ("time", "min", 10, 45)
    assert walk.instructions and db.get(Exercise, "running").instructions


def test_disc_patients_get_the_chair_hamstring_stretch_instead_of_the_floor_one(db):
    for code in DISC:
        kinds = {c["activity_type"]: c for c in plans.candidates(db, [code], age=50, bmi=24)[0]}
        assert "hamstring_stretch" not in kinds, code  # "avoid" on the floor version
        assert kinds["chair_hamstring_stretch"]["verdict"] == "modify"
        assert "straight" in kinds["chair_hamstring_stretch"]["notes"]


def test_older_doses_one_step_lower_never_below_a_step(db):
    allowed, _ = plans.candidates(db, ["none"], age=70, bmi=24)
    by_type = {c["activity_type"]: c for c in allowed}
    assert by_type["walk"]["amount"] == 5 and by_type["calf_raise"]["amount"] == 6
    assert by_type["seated_march"]["amount"] == 3  # 3 - 2 would leave less than one step


FLOOR = {"glute_bridge", "dead_bug", "hamstring_stretch", "quad_stretch"}


def test_floor_exercises_left_out_at_60_or_bmi_30(db):
    for age, bmi, why in ((60, 24, "age 60 >= 60"), (45, 30.0, "BMI 30.0 >= 30")):
        allowed, rules = plans.candidates(db, ["none"], age=age, bmi=bmi)
        kinds = {c["activity_type"] for c in allowed}
        assert not kinds & FLOOR and {"sit_to_stand", "chair_hamstring_stretch"} <= kinds
        line = next(r for r in rules if "(on the floor)" in r)
        assert "Glute Bridge" in line and why in line
    younger = {c["activity_type"] for c in plans.candidates(db, ["none"], age=59, bmi=29.9)[0]}
    assert FLOOR <= younger


def test_floor_rule_reaches_the_rules_only_draft(db):
    exercises, _ = plans.starter_exercises(db, ["chronic_back_pain"], age=70, bmi=24)
    assert exercises and not {e["activity_type"] for e in exercises} & FLOOR


def test_doctor_can_still_add_a_floor_exercise_for_an_older_patient(db):
    chosen = plans.doctor_exercises(db, [{"activity_type": "glute_bridge", "sets": 2, "amount": 5}])
    assert chosen[0]["activity_type"] == "glute_bridge"


def test_high_impact_comes_from_the_exercise_table(db):
    db.get(Exercise, "calf_raise").impact = "high"
    db.flush()
    for age, bmi in ((70, 24), (40, 32)):
        kinds = {c["activity_type"] for c in plans.candidates(db, ["none"], age=age, bmi=bmi)[0]}
        assert not kinds & {"running", "calf_raise"}
    assert "calf_raise" in {c["activity_type"] for c in plans.candidates(db, ["none"], age=40, bmi=24)[0]}
