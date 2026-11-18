"""Thyroid (research/THYROID.md, 2026-11-18): the aliases, "thyroid" with the
type not recorded (thyroid_any: underactive unless the resting pulse is 90+
or overactive wording is found), the hypothyroid grid and its plan. Uses the
real alias and warning files."""
from datetime import date

import pytest
from sqlalchemy import select

from agent.conditions import Finding, load_reference, rule_findings
from agent.routing import THYROID_GUESS_NAME, finalize
from store import plans
from store.models import Condition, ConditionAlias, Exercise, SafetyRule, WarningComplaint
from store.seed import _aliases, _from_csv, _rows

TODAY = date(2026, 11, 18)


@pytest.fixture
def ref(db):
    ref = load_reference(db)
    ref.aliases = [ConditionAlias(**a) for a in _aliases(_from_csv()[0])]
    ref.warnings = [WarningComplaint(phrase=r["phrase"].strip().lower(), label=r["label"])
                    for r in _rows("warning_complaints.csv")]
    return ref


def context(visits=(), history=(), recorded=()):
    return {"visits": list(visits), "vital_flags": [], "alerts": {"emergencies": []},
            "conditions": {"doctor_recorded": [{"name": n} for n in recorded], "long_term_conditions": [],
                           "health_history": [{"item": h} for h in history]},
            "body": {"bmi": 22.0, "measured_on": "2026-11-01"}, "patient": {"age": 40}}


def visit(day, diagnosis=None, complaint=None, **vitals):
    return {"date": day, "diagnosis_provisional": diagnosis, "complaint": complaint, "vitals": vitals}


def assess(ctx, ref, ai_findings=()):
    return finalize(ctx, ref, rule_findings(ctx, ref, TODAY), {"severity": "mild", "problem": "thyroid"},
                    list(ai_findings), TODAY)


def by_code(result):
    return {c["code"]: c for c in result["conditions"]}


# ── Codes and aliases ───────────────────────────────────────────────────────

def test_thyroid_codes_have_the_right_buckets(db):
    assert db.get(Condition, "hypothyroid").bucket == "supported"
    assert db.get(Condition, "hyperthyroid").bucket == "refer"


def test_no_thyroid_wording_still_goes_to_other_unlisted(ref):
    found = [a for a in ref.aliases if "thyro" in a.phrase.lower()]
    assert found and all(a.code in ("hypothyroid", "hyperthyroid", "thyroid_any") for a in found)


@pytest.mark.parametrize("text", ["Hypothyroidism htn", "subclinical hypothyroidism", "hypo thyroid",
                                  "Hashimotos thyroiditis"])
def test_underactive_wording_is_hypothyroid_only(ref, text):
    found = rule_findings(context([visit("2026-11-01", text)]), ref, TODAY)
    codes = {f.code for f in found.findings}
    assert "hypothyroid" in codes and "thyroid_any" not in codes and "other_unlisted" not in codes


@pytest.mark.parametrize("text", ["Hyperthyroidism", "thyrotoxicosis", "Graves disease", "toxic goitre"])
def test_overactive_wording_needs_a_doctor(ref, text):
    out = assess(context([visit("2026-11-01", text)]), ref)
    assert "hyperthyroid" in by_code(out) and out["severity"] == "severe"
    assert any("Overactive thyroid" in r for r in out["severe_reasons"])


def test_recorded_conditions_map_by_name(ref):
    out = assess(context(recorded=["Hypothyroidism"]), ref)
    assert set(by_code(out)) == {"hypothyroid"} and out["severity"] == "mild"
    assert by_code(out)["hypothyroid"]["name"] == "Underactive thyroid"


# ── "Thyroid" with the type not recorded ────────────────────────────────────

def test_bare_thyroid_with_a_normal_pulse_is_treated_as_underactive(ref):
    out = assess(context([visit("2026-11-10", pulse=78)], history=["thyroid"]), ref)
    c = by_code(out)
    assert set(c) == {"hypothyroid"} and out["severity"] == "mild"
    assert c["hypothyroid"]["name"] == THYROID_GUESS_NAME
    assert any("below 90/min" in e for e in c["hypothyroid"]["evidence"])


def test_bare_thyroid_with_no_pulse_is_treated_as_underactive(ref):
    c = by_code(assess(context([visit("2026-11-10", "thyroid")]), ref))
    assert c["hypothyroid"]["name"] == THYROID_GUESS_NAME
    assert any("no resting pulse" in e for e in c["hypothyroid"]["evidence"])


def test_bare_thyroid_with_a_fast_pulse_needs_a_doctor(ref):
    out = assess(context([visit("2026-11-10", pulse=96)], history=["thyroid"]), ref)
    c = by_code(out)
    assert set(c) == {"hyperthyroid"} and out["severity"] == "severe"
    assert any("96/min" in e and "possibly overactive" in e for e in c["hyperthyroid"]["evidence"])


def test_an_old_fast_pulse_doesnt_count(ref):
    out = assess(context([visit("2026-09-01", pulse=110)], history=["thyroid"]), ref)  # older than 30 days
    assert set(by_code(out)) == {"hypothyroid"} and out["severity"] == "mild"


def test_a_fast_pulse_doesnt_change_a_recorded_underactive_thyroid(ref):
    out = assess(context([visit("2026-11-10", "hypothyroidism", pulse=96)]), ref)
    c = by_code(out)
    assert set(c) == {"hypothyroid"} and c["hypothyroid"]["name"] == "Underactive thyroid"


def test_overactive_wins_when_both_are_recorded(ref):
    """0b84894f: recorded "Hyperthyroidism", diagnoses say hypothyroidism."""
    out = assess(context([visit("2026-11-01", "hypothyroidism")], recorded=["Hyperthyroidism"]), ref)
    c = by_code(out)
    assert set(c) == {"hyperthyroid"} and out["severity"] == "severe"
    assert any("stricter reading wins" in e for e in c["hyperthyroid"]["evidence"])


def test_an_ai_quote_of_an_overactive_medicine_overrides_the_guess(ref):
    ai = [Finding("hyperthyroid", "ai", "visit 2026-11-01, medicines", "Carbimazole 10 mg")]
    out = assess(context([visit("2026-11-10", pulse=72)], history=["thyroid"]), ref, ai)
    assert set(by_code(out)) == {"hyperthyroid"} and out["severity"] == "severe"


# ── The grid and the plan ───────────────────────────────────────────────────

def test_hypothyroid_grid_covers_every_exercise(db):
    rules = {r.activity_type: r for r in db.scalars(select(SafetyRule)
                                                     .where(SafetyRule.condition_code == "hypothyroid"))}
    assert set(rules) == set(db.scalars(select(Exercise.activity_type)))
    assert {k for k, r in rules.items() if r.verdict != "safe"} == {
        "glute_bridge", "dead_bug", "neck_isometric", "wall_sit", "running"}
    assert not any(r.verdict == "avoid" for r in rules.values())
    assert sorted(r.usefulness_rank for r in rules.values()) == list(range(1, 34))


def test_hypothyroid_plan_is_walking_strength_balance_breathing(db):
    exercises, _ = plans.starter_exercises(db, ["hypothyroid"], 40, 22.0)
    assert [e["activity_type"] for e in exercises] == [
        "walk", "sit_to_stand", "wall_pushup", "single_leg_stand", "slow_breathing"]
    assert plans.violations(db, exercises, ["hypothyroid"]) == []


def test_hypothyroid_walking_carries_the_trial_evidence(db):
    allowed, _ = plans.candidates(db, ["hypothyroid"], 40, 22.0)
    walk = next(e for e in allowed if e["activity_type"] == "walk")
    assert any("12 weeks" in b for b in walk["benefits"])


def test_hyperthyroid_allows_no_exercise(db):
    allowed, _ = plans.candidates(db, ["hyperthyroid"], 40, 22.0)
    assert allowed == []
