"""Asthma (research/ASTHMA.md, 2026-10-30): the new breathing exercises, the
asthma_controlled grid, and controlled or not from complaints, emergency
visits and SpO2 (never from medicines). Uses the real alias and warning files."""
from datetime import date

import pytest
from sqlalchemy import select

from agent.assess import AIAssessment, AIFinding, _check
from agent.conditions import Finding, load_reference, rule_findings
from agent.routing import finalize
from store import plans
from store.models import Condition, ConditionAlias, Exercise, SafetyRule, WarningComplaint
from store.seed import EXERCISE_PROPERTIES, _aliases, _from_csv, _rows

TODAY = date(2026, 10, 30)
NEW = ["belly_breathing", "pursed_lip_breathing"]
NORMAL = {"bp": {"sys": 125.0, "dia": 80.0, "date": "2026-10-20"}}


@pytest.fixture
def ref(db):
    ref = load_reference(db)
    ref.aliases = [ConditionAlias(**a) for a in _aliases(_from_csv()[0])]
    ref.warnings = [WarningComplaint(phrase=r["phrase"].strip().lower(), label=r["label"])
                    for r in _rows("warning_complaints.csv")]
    return ref


def context(visits=(), history=(), emergencies=()):
    return {"visits": list(visits), "vital_flags": [], "alerts": {"emergencies": list(emergencies)},
            "conditions": {"doctor_recorded": [], "long_term_conditions": [],
                           "health_history": [{"item": h} for h in history]},
            "body": {"bmi": 22.0, "measured_on": "2026-10-01"}}


def visit(day, complaint=None, diagnosis=None, **vitals):
    return {"date": day, "complaint": complaint, "diagnosis_provisional": diagnosis, "vitals": vitals}


def assess(ctx, ref, ai_findings=()):
    return finalize(ctx, ref, rule_findings(ctx, ref, TODAY), {"severity": "mild", "problem": "asthma"},
                    list(ai_findings))


# ── The exercises and the grid ──────────────────────────────────────────────

def test_breathing_exercises_load_as_light_chair_minutes_with_steps(db):
    for kind in NEW:
        ex = db.get(Exercise, kind)
        assert ex is not None and len(ex.instructions) >= 3, kind
        assert (ex.prescription_type, ex.amount_unit, ex.exercise_type) == ("time", "min", "breathing"), kind
        assert (ex.intensity, ex.position, ex.impact, ex.breath_hold) == ("light", "chair", "low", False), kind
        for prop, allowed in EXERCISE_PROPERTIES.items():
            assert getattr(ex, prop) in allowed, (kind, prop)


def test_breathing_exercises_are_safe_for_every_supported_condition(db):
    supported = set(db.scalars(select(Condition.code).where(Condition.bucket == "supported")))
    for kind in NEW:
        rules = list(db.scalars(select(SafetyRule).where(SafetyRule.activity_type == kind)))
        assert {r.condition_code for r in rules} == supported, kind
        assert all(r.verdict == "safe" for r in rules), kind


def test_asthma_codes_have_the_right_buckets(db):
    assert db.get(Condition, "asthma_controlled").bucket == "supported"
    assert db.get(Condition, "asthma_uncontrolled").bucket == "refer"
    assert db.get(Condition, "copd").bucket == "refer"


def test_asthma_grid_covers_every_exercise_and_only_running_is_modify(db):
    rules = {r.activity_type: r for r in db.scalars(select(SafetyRule)
                                                     .where(SafetyRule.condition_code == "asthma_controlled"))}
    assert set(rules) == set(db.scalars(select(Exercise.activity_type)))
    assert {k for k, r in rules.items() if r.verdict != "safe"} == {"running"}
    assert "cold, smoky or dusty" in rules["running"].note


def test_asthma_list_puts_walking_strength_and_breathing_first(db):
    first = [c["activity_type"] for c in plans.candidates(db, ["asthma_controlled"], age=50, bmi=24,
                                                           readings=NORMAL)[0]][:7]
    assert first == ["walk", "march_in_place", "sit_to_stand", "wall_pushup", "calf_raise", "belly_breathing",
                     "pursed_lip_breathing"]


def test_running_never_reaches_an_older_asthma_patient(db):
    kinds = {c["activity_type"] for c in plans.candidates(db, ["asthma_controlled"], age=65, bmi=24,
                                                          readings=NORMAL)[0]}
    assert "running" not in kinds and "belly_breathing" in kinds


def test_asthma_with_bp_takes_the_stricter_verdict_and_both_notes(db):
    by_type = {c["activity_type"]: c for c in plans.candidates(db, ["asthma_controlled", "bp_controlled"], age=50,
                                                               bmi=24, readings=NORMAL)[0]}
    assert by_type["wall_sit"]["verdict"] == "modify"  # safe for asthma, modify for BP
    assert "cold, smoky or dusty" in by_type["running"]["notes"] and "blood pressure" in by_type["running"]["notes"]


# ── Finding asthma, and controlled or not ───────────────────────────────────

@pytest.mark.parametrize("ctx", [
    context(history=["asthma"]),
    context(visits=[visit("2026-09-01", diagnosis="Htn, bronchial asthma")]),
])
def test_asthma_with_no_signs_is_controlled_and_supported(ref, ctx):
    out = assess(ctx, ref)
    assert "asthma_controlled" in out["codes"] and "asthma_uncontrolled" not in out["codes"]
    assert not any("sthma" in r for r in out["severe_reasons"])


@pytest.mark.parametrize("ctx, why", [
    (context(history=["asthma"], visits=[visit("2026-09-01", complaint="Breathing difficulty, cough")]),
     "breathlessness"),
    (context(history=["asthma"], visits=[visit("2026-09-01", complaint="Wheezing since 2 days")]), "wheeze"),
    (context(history=["asthma"], emergencies=[{"date": "2026-08-01"}]), "emergency visit"),
    (context(history=["asthma"], visits=[visit("2026-10-01", spo2=92)]), "SpO2 92%"),
])
def test_asthma_with_a_sign_is_not_controlled_and_severe(ref, ctx, why):
    out = assess(ctx, ref)
    assert "asthma_uncontrolled" in out["codes"] and "asthma_controlled" not in out["codes"]
    assert out["severity"] == "severe"
    asthma = next(c for c in out["conditions"] if c["code"] == "asthma_uncontrolled")
    assert any(why in line for line in asthma["evidence"]), asthma["evidence"]


def test_only_the_latest_spo2_counts(ref):
    ctx = context(history=["asthma"], visits=[visit("2026-10-20", spo2="96%"), visit("2026-08-01", spo2=93)])
    assert "asthma_controlled" in assess(ctx, ref)["codes"]


def test_breathlessness_older_than_six_months_doesnt_count(ref):
    ctx = context(history=["asthma"], visits=[visit("2026-02-01", complaint="breathlessness")])
    assert "asthma_controlled" in assess(ctx, ref)["codes"]


def test_wheeze_is_a_warning_complaint_for_everyone(ref):
    out = assess(context(visits=[visit("2026-10-01", complaint="wheeze at night")]), ref)
    assert out["severity"] == "severe" and any("Wheeze" in r for r in out["severe_reasons"])


@pytest.mark.parametrize("text", ["COPD", "COAD", "chronic bronchitis", "Emphysema"])
def test_copd_is_its_own_refer_code(ref, text):
    out = assess(context(visits=[visit("2026-09-01", diagnosis=text)]), ref)
    assert "copd" in out["codes"] and "other_unlisted" not in out["codes"] and out["severity"] == "severe"


def test_the_ai_cannot_make_asthma_controlled_when_the_rules_say_not(ref):
    ctx = context(history=["asthma"], visits=[visit("2026-09-01", complaint="breathlessness")])
    rules = rule_findings(ctx, ref, TODAY)
    out = finalize(ctx, ref, rules, {"severity": "mild", "problem": "asthma"},
                   [Finding("asthma_controlled", "ai", "health history", "asthma")])
    assert "asthma_uncontrolled" in out["codes"] and "asthma_controlled" not in out["codes"]


def test_an_ai_uncontrolled_needs_the_record_to_say_so(ref):
    record = {"history": "asthma", "visit": "acute exacerbation of asthma"}
    answer = AIAssessment(conditions=[AIFinding(code="asthma_uncontrolled", quote="asthma", where="health history"),
                                      AIFinding(code="asthma_uncontrolled", quote="acute exacerbation of asthma",
                                                where="visit 2026-10-01, diagnosis")],
                          problem="asthma", body_area="chest", severity="mild", concerns=[], missing=[])
    kept, dropped, _ = _check(answer, ref, record)
    assert [f.code for f in kept] == ["asthma_any", "asthma_uncontrolled"] and not dropped
