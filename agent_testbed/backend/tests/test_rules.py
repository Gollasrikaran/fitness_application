"""The safety rules for plans (store.plans) and severity (agent.routing)."""
from itertools import combinations

from sqlalchemy import select

from agent.conditions import Finding, RuleResult, load_reference
from agent.routing import finalize
from store import plans
from store.models import Condition, Exercise, SafetyRule


def supported(db) -> list[str]:
    return list(db.scalars(select(Condition.code).where(Condition.bucket == "supported")))


def refer(db) -> list[str]:
    return list(db.scalars(select(Condition.code).where(Condition.bucket == "refer")))


def avoid_pairs(db) -> set[tuple[str, str]]:
    return {(r.condition_code, r.activity_type) for r in db.scalars(select(SafetyRule).where(SafetyRule.verdict == "avoid"))}


def test_grid_has_avoid_rules_to_test(db):
    assert avoid_pairs(db), "the tests below need at least one avoid rule in data/safety_grid.csv"


def test_starter_never_has_avoid_or_dose_over_max(db):
    """Every supported condition, alone and in pairs, at any age or BMI."""
    codes = supported(db)
    avoid = avoid_pairs(db)
    maxima = {e.activity_type: e for e in db.scalars(select(Exercise))}
    for combo in [[c] for c in codes] + [list(p) for p in combinations(codes, 2)]:
        for age, bmi in ((30, 22.0), (70, 22.0), (40, 34.0), (None, None)):
            exercises, _ = plans.starter_exercises(db, combo, age, bmi)
            assert plans.violations(db, exercises, combo) == [], combo
            for x in exercises:
                assert all((c, x["activity_type"]) not in avoid for c in combo), (combo, x)
                assert x["sets"] <= maxima[x["activity_type"]].max_sets
                assert x["amount"] <= maxima[x["activity_type"]].max_amount


def test_candidates_leave_out_avoid(db):
    for code, kind in avoid_pairs(db):
        allowed, _ = plans.candidates(db, [code], 40, 22.0)
        assert kind not in {e["activity_type"] for e in allowed}


def test_refer_condition_allows_nothing(db):
    for code in refer(db):
        assert plans.approved_exercises(db, [code]) == []
        assert plans.approved_exercises(db, [code, "chronic_back_pain"]) == []


def test_running_left_out_for_older_or_high_bmi(db):
    for age, bmi in ((65, 22.0), (40, 31.0)):
        allowed, rules = plans.candidates(db, ["none"], age, bmi)
        assert "running" not in {e["activity_type"] for e in allowed}
        assert rules


def entry(db, kind, **dose):
    e = db.get(Exercise, kind)
    return {"activity_type": kind, "name": e.display_name, "unit": e.amount_unit,
            "sets": dose.get("sets", e.default_sets), "amount": dose.get("amount", e.default_amount), "notes": ""}


def test_violations_catch_avoid(db):
    code, kind = sorted(avoid_pairs(db))[0]
    assert any("avoid" in p for p in plans.violations(db, [entry(db, kind)], [code]))


def test_violations_catch_dose_over_max(db):
    walk = db.get(Exercise, "walk")
    assert plans.violations(db, [entry(db, "walk", sets=walk.max_sets + 1)], ["none"])
    assert plans.violations(db, [entry(db, "walk", amount=walk.max_amount + 0.5)], ["none"])
    assert plans.violations(db, [entry(db, "walk", sets=0)], ["none"])
    assert plans.violations(db, [entry(db, "walk", amount=0)], ["none"])
    assert plans.violations(db, [entry(db, "walk", amount=walk.max_amount)], ["none"]) == []


def test_violations_catch_unknown_refer_and_duplicates(db):
    unknown = {"activity_type": "burpees", "name": "Burpees", "unit": "count", "sets": 1, "amount": 1, "notes": ""}
    assert plans.violations(db, [unknown], ["none"])
    assert plans.violations(db, [entry(db, "walk")], ["high_bp"])
    assert plans.violations(db, [entry(db, "walk")], ["not_a_code"])
    assert plans.violations(db, [entry(db, "walk"), entry(db, "walk")], ["none"])
    six = [entry(db, k) for k in ("walk", "glute_bridge", "shoulder_circles", "ankle_circles", "wrist_circles",
                                  "calf_stretch")]
    assert any("at most" in p for p in plans.violations(db, six, ["none"]))


# ── Severity (agent.routing.finalize) ────────────────────────────────────────

def context(**over):
    base = {"visits": [], "vital_flags": [], "alerts": {"emergencies": []},
            "conditions": {"doctor_recorded": []}}
    return {**base, **over}


def ai(severity, problem="knee pain"):
    return {"severity": severity, "problem": problem}


def test_refer_condition_is_severe_whatever_the_ai_says(db):
    ref = load_reference(db)
    rules = RuleResult(findings=[Finding("heart_condition", "rules", "visit 2026-10-01, diagnosis", "IHD")])
    out = finalize(context(), ref, rules, ai("mild"), [])
    assert out["severity"] == "severe"


def test_ai_cannot_remove_a_rule_condition(db):
    ref = load_reference(db)
    rules = RuleResult(findings=[Finding("arthritis_knee", "rules", "visit 2026-10-01, diagnosis", "oa knee")])
    out = finalize(context(), ref, rules, ai("mild"), [])
    assert "arthritis_knee" in out["codes"]


def test_unknown_clinic_condition_becomes_other_unlisted(db):
    ref = load_reference(db)
    out = finalize(context(), ref, RuleResult(unmapped=["doctor recorded: Hypothyroidism"]), ai("mild"), [])
    assert "other_unlisted" in out["codes"] and out["severity"] == "severe"


def test_condition_recorded_severe_by_a_doctor_is_severe(db):
    ref = load_reference(db)
    recorded = [{"name": "Osteoarthritis", "severity": "SEVERE", "status": "ACTIVE"}]
    out = finalize(context(conditions={"doctor_recorded": recorded}), ref, RuleResult(), ai("mild"), [])
    assert out["severity"] == "severe"
    assert any("Recorded by a doctor as severe" in r for r in out["severe_reasons"])


def test_ai_severe_makes_it_severe(db):
    out = finalize(context(), load_reference(db), RuleResult(), ai("severe"), [])
    assert out["severity"] == "severe"


def test_no_reason_keeps_the_ai_severity(db):
    out = finalize(context(), load_reference(db), RuleResult(), ai("mild"), [])
    assert (out["severity"], out["codes"]) == ("mild", ["none"])
