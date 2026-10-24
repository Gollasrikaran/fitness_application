"""Plan drafting (agent.draft): whatever the AI returns, no saved draft ever
holds an "avoid" exercise or a dose above the maximum."""
import random
from itertools import combinations

from sqlalchemy import select

from agent.draft import AIDraft, AIPick, build_draft
from store import plans
from store.models import Condition, Exercise, Plan, SafetyRule

PATIENT = {"age": 45, "sex": "F", "bmi": 24.0}


def assessment(codes, severity="moderate", reasons=()):
    return {"id": "assessment-1", "codes": codes, "severity": severity, "severe_reasons": list(reasons),
            "problem": "knee pain on walking", "body_area": "knee", "concerns": [],
            "conditions": [{"code": c, "name": c} for c in codes]}


def ai_picking(*kinds, instructions="Go slowly. Stop and phone your doctor if it hurts."):
    def ask(_assessment, _patient, _allowed):
        return AIDraft(exercises=[AIPick(activity_type=k, why="helps") for k in kinds],
                       instructions=instructions, reason="Gentle start.")
    return ask


def ai_down(*_):
    raise TimeoutError("no answer")


def ai_must_not_run(*_):
    raise AssertionError("the AI must not be asked for a severe case")


def safe_pick(db, code, n=3):
    allowed, _ = plans.candidates(db, [code], PATIENT["age"], PATIENT["bmi"])
    return [e["activity_type"] for e in allowed[:n]]


def an_avoid(db):
    r = db.scalars(select(SafetyRule).where(SafetyRule.verdict == "avoid").order_by(SafetyRule.id)).first()
    return r.condition_code, r.activity_type


def test_severe_gets_no_ai_draft(db):
    a = assessment(["arthritis_knee"], "severe", ["Chest pain in the complaint on 2026-10-01"])
    p = build_draft(db, "p1", a, PATIENT, ask_ai=ai_must_not_run)
    assert (p.source, p.exercises, p.assessment_id) == ("doctor", [], "assessment-1")
    assert "Chest pain" in p.reason


def test_refer_code_gets_no_draft_even_if_not_marked_severe(db):
    p = build_draft(db, "p1", assessment(["high_bp"]), PATIENT, ask_ai=ai_must_not_run)
    assert (p.source, p.exercises) == ("doctor", [])


def test_good_ai_draft_is_kept_at_the_rules_doses(db):
    kinds = safe_pick(db, "arthritis_knee")
    p = build_draft(db, "p1", assessment(["arthritis_knee"]), PATIENT, ask_ai=ai_picking(*kinds))
    assert p.source == "ai" and [e["activity_type"] for e in p.exercises] == kinds
    for e in p.exercises:
        ex = db.get(Exercise, e["activity_type"])
        assert (e["sets"], e["amount"]) == (ex.default_sets, ex.default_amount)
    assert p.kind == "starter" and p.status == "pending" and p.instructions


def test_ai_picking_an_avoid_exercise_falls_back_to_rules(db):
    code, kind = an_avoid(db)
    p = build_draft(db, "p1", assessment([code]), PATIENT, ask_ai=ai_picking(*safe_pick(db, code, 2), kind))
    assert p.source == "rules"
    assert kind not in {e["activity_type"] for e in p.exercises}
    assert "AI draft not used" in p.reason


def test_ai_picking_an_unknown_exercise_falls_back_to_rules(db):
    p = build_draft(db, "p1", assessment(["chronic_back_pain"]), PATIENT, ask_ai=ai_picking("walk", "burpees"))
    assert p.source == "rules" and plans.violations(db, p.exercises, ["chronic_back_pain"]) == []


def test_ai_too_many_or_duplicate_or_no_instructions_falls_back(db):
    six = [e.activity_type for e in db.scalars(select(Exercise).order_by(Exercise.priority_order))][:6]
    for ask in (ai_picking(*six), ai_picking("walk", "walk"), ai_picking("walk", instructions=" "), ai_picking()):
        p = build_draft(db, "p1", assessment(["none"]), PATIENT, ask_ai=ask)
        assert p.source == "rules", ask


def test_ai_down_falls_back_to_rules(db):
    p = build_draft(db, "p1", assessment(["chronic_back_pain"]), PATIENT, ask_ai=ai_down)
    assert p.source == "rules" and p.exercises and "unavailable" in p.reason


def test_new_draft_replaces_the_pending_one(db):
    first = build_draft(db, "p1", assessment(["none"]), PATIENT, ask_ai=ai_down)
    second = build_draft(db, "p1", assessment(["none"]), PATIENT, ask_ai=ai_down)
    assert first.status == "superseded" and second.status == "pending"
    assert plans.pending_proposal(db, "p1").id == second.id


def test_patient_with_a_plan_gets_an_update_with_changes(db):
    old = Plan(patient_id="p1", doctor_id="d1", instructions="old",
               exercises=[{"activity_type": "running", "name": "Running", "unit": "km", "sets": 1, "amount": 1.0,
                           "notes": ""}], conditions=["none"])
    db.add(old)
    db.flush()
    p = build_draft(db, "p1", assessment(["arthritis_knee"]), PATIENT, ask_ai=ai_picking("walk", "glute_bridge"))
    assert (p.kind, p.based_on_plan_id) == ("update", old.id)
    notes = {(c["activity_type"], c["note"]) for c in p.changes}
    assert ("running", "Removed") in notes and ("walk", "Added") in notes


def test_no_draft_ever_breaks_the_rules(db):
    """Random AI answers (any exercise, junk, duplicates, too many) for random
    condition sets and patients: every saved draft passes the rules."""
    rng = random.Random(5)
    codes = list(db.scalars(select(Condition.code)))
    kinds = list(db.scalars(select(Exercise.activity_type))) + ["burpees", ""]
    avoid = {(r.condition_code, r.activity_type)
             for r in db.scalars(select(SafetyRule).where(SafetyRule.verdict == "avoid"))}
    maxima = {e.activity_type: e for e in db.scalars(select(Exercise))}
    combos = [[c] for c in codes] + [list(p) for p in combinations(codes, 2)]
    for i in range(600):
        combo = rng.choice(combos)
        patient = {"age": rng.choice([None, 25, 59, 60, 80]), "sex": "M", "bmi": rng.choice([None, 21.0, 30.0, 38.5])}
        ask = rng.choice([ai_down, ai_picking(*rng.sample(kinds, rng.randint(0, 7)))])
        p = build_draft(db, f"p{i}", assessment(combo, rng.choice(["mild", "moderate"])), patient, ask_ai=ask)
        assert plans.violations(db, p.exercises, combo) == [] or p.exercises == []
        for e in p.exercises:
            assert all((c, e["activity_type"]) not in avoid for c in combo)
            assert e["sets"] <= maxima[e["activity_type"]].max_sets
            assert e["amount"] <= maxima[e["activity_type"]].max_amount
        if any(db.get(Condition, c).bucket == "refer" for c in combo):
            assert p.source == "doctor" and p.exercises == []
