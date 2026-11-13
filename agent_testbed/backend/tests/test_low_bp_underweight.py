"""Low BP and underweight (2026-11-13, provisional; QUESTIONS_FOR_DOCTOR.md
1b and 5.4, sources in research/SOURCES_LOW_BP_UNDERWEIGHT_CKD.md).

- BP below 90/60: floor and vigorous exercises left out (data/reading_rules.csv).
- The clinic's BP LOW flags and a "hypotension" diagnosis: a concern.
- BMI below 18.5: vigorous left out, strength and balance first, a concern.
- BMI below 16: a doctor writes the plan."""
from sqlalchemy import select

import pytest

from agent.conditions import RuleResult, load_reference
from agent.routing import finalize
from store import plans
from store.models import Exercise

FLOOR = {"glute_bridge", "dead_bug", "hamstring_stretch", "quad_stretch"}


def bp(sys_, dia):
    return {"bp": {"sys": float(sys_), "dia": float(dia), "date": "2026-11-01"}}


def allowed(db, readings=None, age=50, bmi=24.0, codes=("none",)):
    out, lines = plans.candidates(db, list(codes), age, bmi, readings)
    return [e["activity_type"] for e in out], lines


def context(bmi=None, flags=(), visits=()):
    return {"visits": list(visits), "vital_flags": list(flags), "alerts": {"emergencies": []},
            "conditions": {"doctor_recorded": [], "long_term_conditions": [], "health_history": []},
            "body": {"bmi": bmi, "measured_on": "2026-10-01"}, "patient": {"age": 50}}


def assess(db, ctx):
    return finalize(ctx, load_reference(db), RuleResult(), {"severity": "mild", "problem": "x"}, [])


# ── Low BP: the reading rule ────────────────────────────────────────────────

@pytest.mark.parametrize("reading", [(85, 63), (110, 55), (88, 70)])
def test_low_bp_leaves_out_floor_and_vigorous(db, reading):
    kinds, lines = allowed(db, bp(*reading))
    assert not FLOOR & set(kinds) and "running" not in kinds
    assert any("is low" in line for line in lines)
    assert "walk" in kinds  # not a stop on its own


@pytest.mark.parametrize("reading", [(90, 60), (120, 80)])
def test_normal_bp_changes_nothing(db, reading):
    kinds, lines = allowed(db, bp(*reading))
    assert FLOOR <= set(kinds) and "running" in kinds and not lines


def test_ai_draft_with_a_floor_exercise_at_low_bp_breaks_the_rules(db):
    problems = plans.violations(db, [{"activity_type": "glute_bridge", "sets": 2, "amount": 5}], ["none"], bp(85, 63))
    assert any("is low" in p for p in problems)


def test_doctor_only_gets_a_warning_at_low_bp(db):
    warn = plans.doctor_warnings(db, [{"activity_type": "dead_bug", "sets": 2, "amount": 4}], ["none"], bp(85, 63))
    assert any(w.startswith("Not advised") for w in warn["dead_bug"])


# ── Low BP: concerns for the doctor ─────────────────────────────────────────

def test_clinic_low_bp_flag_is_a_concern_not_a_stop(db):
    out = assess(db, context(flags=[{"code": "BP_SYS_LOW", "severity": "ABNORMAL", "date": "2026-09-01",
                                     "value": "85"}]))
    assert any(c.startswith("Clinic flagged low BP: BP_SYS_LOW") for c in out["concerns"])
    assert out["severity"] != "severe"


def test_hypotension_diagnosis_is_a_concern(db):
    visit = {"date": "2026-09-16", "complaint": "Dizziness", "diagnosis_provisional": "Hypotension"}
    out = assess(db, context(visits=[visit]))
    assert any(c.startswith("Low BP in the diagnosis") for c in out["concerns"])


def test_high_bp_flag_is_not_a_low_bp_concern(db):
    out = assess(db, context(flags=[{"code": "BP_SYS_HIGH", "severity": "ABNORMAL", "date": "2026-09-01"}]))
    assert not any("low BP" in c for c in out["concerns"])


# ── Underweight ─────────────────────────────────────────────────────────────

def test_underweight_leaves_out_vigorous_and_puts_strength_and_balance_first(db):
    out, lines = plans.candidates(db, ["none"], 50, 17.3)
    assert "running" not in {e["activity_type"] for e in out}
    types = {e.activity_type: e.exercise_type for e in db.scalars(select(Exercise))}
    safe = [types[e["activity_type"]] in ("strength", "balance") for e in out if e["verdict"] == "safe"]
    assert any(safe) and safe == sorted(safe, reverse=True)  # every strength/balance before the rest
    assert any("left out (vigorous)" in line for line in lines)
    assert any(line.startswith("Strength and balance exercises first") for line in lines)


def test_rules_draft_for_underweight_starts_with_walking_then_strength(db):
    exercises, _ = plans.starter_exercises(db, ["none"], 50, 17.3)
    types = {e.activity_type: e.exercise_type for e in db.scalars(select(Exercise))}
    assert exercises[0]["activity_type"] == "walk"
    assert all(types[x["activity_type"]] in ("strength", "balance") for x in exercises[1:])


def test_normal_bmi_changes_nothing(db):
    assert allowed(db, bmi=24.0) == allowed(db, bmi=None)


@pytest.mark.parametrize("bmi, severe, concern", [(15.2, True, False), (16.0, False, True), (18.4, False, True),
                                                  (18.5, False, False), (None, False, False)])
def test_bmi_severity_and_concern(db, bmi, severe, concern):
    out = assess(db, context(bmi=bmi))
    assert (out["severity"] == "severe") == severe
    assert any("severe thinness" in r for r in out["severe_reasons"]) == severe
    assert any(c.startswith("Underweight") for c in out["concerns"]) == concern
