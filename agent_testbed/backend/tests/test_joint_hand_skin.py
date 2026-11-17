"""Joint, back, hand and skin (2026-11-17, PROPOSED_CHANGES_2026-11-17.md;
research/JOINT_AND_BACK_PAIN.md, research/SKIN.md).

- Alias overlap: a short alias found inside a longer one at the same place
  is dropped ("knee joint pain" is knee pain only); one alias row may carry
  several codes ("djd knee spine": knee and spine).
- New aliases, warning complaints and conditions (hand_pain,
  skin_condition, skin_infection), and 6 exercises with their grid rows.
- Hand exercises only for hand or wrist pain, in a hand slot that takes the
  upper-body slot's place."""
from datetime import date

import pytest
from sqlalchemy import select

from agent.conditions import load_reference, longest_matches, rule_findings, words
from store import plans
from store.models import Condition, ConditionAlias, Exercise, SafetyRule, WarningComplaint
from store.seed import EXERCISE_PROPERTIES, _aliases, _from_csv, _rows, time_windows

TODAY = date(2026, 11, 17)
HAND = ["fist_open", "finger_spread", "thumb_touch", "towel_squeeze"]
NEW = HAND + ["wall_pelvic_tilt", "mini_squat"]
NORMAL = {"bp": {"sys": 125.0, "dia": 80.0, "date": "2026-11-01"}}


@pytest.fixture
def ref(db):
    ref = load_reference(db)
    ref.aliases = [ConditionAlias(**a) for a in _aliases(_from_csv()[0])]
    ref.warnings = [WarningComplaint(phrase=r["phrase"].strip().lower(), label=r["label"])
                    for r in _rows("warning_complaints.csv")]
    ref.windows = {(w["what"], w["counts_from"]): w["days"] for w in time_windows(_from_csv()[0])}
    return ref


def context(*visits):
    return {"visits": list(visits), "vital_flags": [], "alerts": {"emergencies": []},
            "conditions": {"doctor_recorded": [], "long_term_conditions": [], "health_history": []},
            "body": {"bmi": None}, "patient": {"age": 46}}


def found(ref, diagnosis=None, complaint=None, day="2026-11-01"):
    out = rule_findings(context({"date": day, "diagnosis_provisional": diagnosis, "complaint": complaint}), ref, TODAY)
    return {f.code for f in out.findings}, out


# ── Alias overlap ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("Knee joint pain since 1 month", {"arthritis_knee"}),  # KNOWN_ISSUES.md #1: no longer "joint pain" too
    ("pre diabetes", {"prediabetes"}),  # was also diabetes
    ("uncontrolled htn", {"high_bp"}),
    ("DJD knee spine", {"arthritis_knee", "spondylosis"}),  # one alias, two codes
    ("DJD spine and knee", {"arthritis_knee", "spondylosis"}),
    ("Knee arthitis", {"arthritis_knee"}),  # not also bare "arthritis"
    ("osteoarthritis knee", {"arthritis_knee"}),
    ("Multiple joint pain under evaluation", {"other_unlisted"}),
    ("Arthritis", {"other_unlisted"}),
    ("DJD", {"other_unlisted"}),
    ("knee pain, joint pain in fingers", {"arthritis_knee", "other_unlisted"}),  # two places: both count
])
def test_overlapping_aliases(ref, text, expected):
    assert found(ref, diagnosis=text)[0] == expected


def test_a_shorter_alias_still_counts_where_it_stands_alone():
    phrases = [(words("joint pain"), "other_unlisted"), (words("knee joint pain"), "arthritis_knee")]
    assert longest_matches(words("knee joint pain, hip joint pain"), phrases) == phrases  # both places


def test_multi_code_rows_load_as_one_alias_per_code():
    rows = [a for a in _aliases(_from_csv()[0]) if a["phrase"] == "djd knee spine"]
    assert {a["code"] for a in rows} == {"spondylosis", "arthritis_knee"}


# ── New aliases and warnings ────────────────────────────────────────────────

@pytest.mark.parametrize("text, code", [
    ("Hand pain", "hand_pain"), ("finger joint pain", "hand_pain"), ("trigger finger", "hand_pain"),
    ("Eczema", "skin_condition"), ("LSC", "skin_condition"), ("Reecalcitrant Tinea", "skin_condition"),
    ("fungal infection", "skin_condition"), ("psoriasis", "skin_condition"),
    ("Herpes zoster", "skin_infection"), ("cellulitis leg", "skin_infection"),
    ("LBA", "chronic_back_pain"), ("acute lumbago", "chronic_back_pain"), ("oa knees", "arthritis_knee"),
    ("lumbar radiculopathy", "neurological"), ("HT", "bp_any"),
])
def test_new_aliases(ref, text, code):
    assert code in found(ref, diagnosis=text)[0]


def test_bp_shorthand_resolves_like_htn(ref):
    assert "bp_any" in found(ref, diagnosis="HT, T2DM")[0]


@pytest.mark.parametrize("complaint, warned", [
    ("weakness in legs since 2 days", True), ("foot drop", True), ("loss of bladder control", True),
    ("general weakness", False), ("hand pain", False),
])
def test_back_red_flags_are_warning_complaints(ref, complaint, warned):
    labels = {w["label"] for w in found(ref, complaint=complaint)[1].warnings}
    assert ("Leg weakness or bladder change" in labels) == warned


def test_a_skin_infection_counts_for_30_days(ref):
    assert "skin_infection" in found(ref, diagnosis="Herpes zoster", day="2026-11-01")[0]
    codes, out = found(ref, diagnosis="Herpes zoster", day="2026-09-01")
    assert "skin_infection" not in codes and any("older than 30 days" in e for e in out.expired)


# ── Conditions and exercises ────────────────────────────────────────────────

def test_new_conditions(db):
    assert db.get(Condition, "hand_pain").bucket == "supported"
    assert db.get(Condition, "skin_condition").bucket == "supported"
    assert db.get(Condition, "skin_infection").bucket == "refer"
    assert "dry well" in db.get(Condition, "skin_condition").notes
    assert "tingles" in db.get(Condition, "chronic_back_pain").notes


def test_new_exercises_load_with_steps_and_known_properties(db):
    for kind in NEW:
        ex = db.get(Exercise, kind)
        assert ex is not None and len(ex.instructions) >= 3, kind
        assert 1 <= ex.default_sets <= ex.max_sets and 0 < ex.default_amount <= ex.max_amount, kind
        for prop, allowed in EXERCISE_PROPERTIES.items():
            assert getattr(ex, prop) in allowed, (kind, prop)
        assert ex.impact == "low" and ex.intensity == "light" and not ex.breath_hold, kind
        assert ex.position in ("standing", "chair"), kind
    assert {db.get(Exercise, k).body_part for k in HAND} == {"hand"}


def test_new_exercises_have_a_verdict_for_every_supported_condition_and_no_avoid(db):
    supported = set(db.scalars(select(Condition.code).where(Condition.bucket == "supported")))
    for kind in NEW:
        rules = list(db.scalars(select(SafetyRule).where(SafetyRule.activity_type == kind)))
        assert {r.condition_code for r in rules} == supported, kind
        assert all(r.verdict != "avoid" for r in rules), kind


def test_new_conditions_rank_every_exercise_once(db):
    for code in ("hand_pain", "skin_condition", "chronic_back_pain", "carpal_tunnel"):
        ranks = sorted(db.scalars(select(SafetyRule.usefulness_rank).where(SafetyRule.condition_code == code)))
        assert ranks == list(range(1, 34)), code


def verdicts(db, code):
    return {r.activity_type: r for r in db.scalars(select(SafetyRule).where(SafetyRule.condition_code == code))}


def test_grid_exceptions(db):
    assert verdicts(db, "arthritis_knee")["mini_squat"].verdict == "modify"
    assert verdicts(db, "arthritis_knee")["mini_squat"].usefulness_rank == 4
    for kind in ("glute_bridge", "dead_bug"):
        assert "floor" in verdicts(db, "arthritis_knee")[kind].note and \
            verdicts(db, "arthritis_knee")[kind].verdict == "modify"
    assert verdicts(db, "hand_pain")["wall_pushup"].verdict == "modify"
    assert verdicts(db, "skin_condition")["running"].verdict == "modify"
    assert verdicts(db, "carpal_tunnel")["towel_squeeze"].verdict == "modify"
    assert "hold your breath" in verdicts(db, "bp_controlled")["towel_squeeze"].note
    assert verdicts(db, "spondylosis")["wall_pelvic_tilt"].usefulness_rank == 3


def first(db, code, n=5):
    return [c["activity_type"] for c in plans.candidates(db, [code], age=46, bmi=22, readings=NORMAL)[0]][:n]


def test_back_pain_puts_walking_and_the_wall_pelvic_tilt_first(db):
    assert first(db, "chronic_back_pain", 4) == ["walk", "march_in_place", "wall_pelvic_tilt", "sit_to_stand"]


# ── Plans: the hand slot ────────────────────────────────────────────────────

def slots(db, codes):
    allowed, _ = plans.candidates(db, codes, 46, 22, NORMAL)
    return {name: [e["activity_type"] for e in options] for name, options in plans.plan_slots(allowed)}, allowed


@pytest.mark.parametrize("codes", [["none"], ["arthritis_knee"], ["bp_controlled"], ["skin_condition"]])
def test_no_hand_exercises_without_hand_pain(db, codes):
    s, allowed = slots(db, codes)
    assert not {e["activity_type"] for e in allowed} & set(HAND)
    assert "hand" not in s and "upper-body strength" in s


@pytest.mark.parametrize("codes", [["hand_pain"], ["carpal_tunnel"], ["hand_pain", "arthritis_knee"]])
def test_hand_patients_get_a_hand_slot_instead_of_upper_body(db, codes):
    s, allowed = slots(db, codes)
    assert "upper-body strength" not in s
    assert s["hand"] and set(s["hand"]) <= set(HAND)
    plan = [e["activity_type"] for e in plans.balanced_plan(allowed)]
    assert plan[0] == "walk" and len(plan) <= plans.MAX_EXERCISES
    assert "wall_pushup" not in plan and sum(k in HAND for k in plan) == 1


def test_hand_pain_plan(db):
    allowed, _ = plans.candidates(db, ["hand_pain"], 46, 22, NORMAL)
    assert [e["activity_type"] for e in plans.balanced_plan(allowed)] == [
        "walk", "glute_bridge", "fist_open", "single_leg_stand", "slow_breathing"]  # leg slot: the general order


def test_hand_plan_passes_the_rules(db):
    exercises, _ = plans.starter_exercises(db, ["hand_pain"], 46, 22, readings=NORMAL)
    assert plans.violations(db, exercises, ["hand_pain"], NORMAL) == []
