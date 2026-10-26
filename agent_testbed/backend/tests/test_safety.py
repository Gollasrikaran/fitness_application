"""Phase 8 safety tests (agent.routing, agent.conditions, agent.assess._check):
whatever the AI says, the rules' severity stands; BP and sugar control
follows the clinic's flags; warning complaints; the AI quote checks."""
import random
from datetime import date

import pytest

from agent.assess import AIAssessment, AIFinding, _check
from agent.conditions import Finding, RuleResult, load_reference, rule_findings
from agent.routing import finalize
from store.models import ConditionAlias, WarningComplaint

TODAY = date(2026, 10, 26)
RANK = {"mild": 0, "moderate": 1, "severe": 2}


@pytest.fixture
def ref(db):
    ref = load_reference(db)
    ref.aliases = [ConditionAlias(source="text", phrase="htn", code="bp_any"),
                   ConditionAlias(source="text", phrase="t2dm", code="diabetes_any"),
                   ConditionAlias(source="text", phrase="oa knee", code="arthritis_knee"),
                   ConditionAlias(source="text", phrase="knee pain", code="arthritis_knee")]
    ref.warnings = [WarningComplaint(phrase="chest pain", label="Chest pain"),
                    WarningComplaint(phrase="dizziness", label="Dizziness")]
    return ref


def context(visits=(), flags=(), emergencies=(), recorded=(), bmi=None):
    return {"visits": list(visits), "vital_flags": list(flags), "alerts": {"emergencies": list(emergencies)},
            "conditions": {"doctor_recorded": list(recorded), "long_term_conditions": [], "health_history": []},
            "body": {"bmi": bmi, "measured_on": "2026-10-01"}}


def visit(day, complaint=None, diagnosis=None, **vitals):
    return {"date": day, "complaint": complaint, "diagnosis_provisional": diagnosis, "vitals": vitals}


def flag(code, severity, day, value=0):
    return {"code": code, "severity": severity, "date": day, "value": value}


def ai(severity="mild"):
    return {"severity": severity, "problem": "knee pain"}


def assess(ctx, ref, ai_answer=None, ai_findings=(), rules=None):
    rules = rules or rule_findings(ctx, ref, TODAY)
    return finalize(ctx, ref, rules, ai_answer if ai_answer is not None else ai(), list(ai_findings))


# ── The AI can't lower what the rules decided ───────────────────────────────

@pytest.mark.parametrize("ctx, reason", [
    (context(flags=[flag("SPO2_CRITICAL", "CRITICAL", "2026-10-20", 87)]), "Critical vital"),
    (context(emergencies=[{"date": "2026-10-01"}]), "Emergency visit"),
    (context(visits=[visit("2026-10-20", complaint="Chest pain since 2 days")]), "Chest pain"),
    (context(visits=[visit("2026-10-20", diagnosis="HTN", bp="160/100")],
             flags=[flag("BP_SYS_HIGH", "HIGH", "2026-10-20")]), "needs a doctor"),
])
def test_rules_severe_stays_severe_when_the_ai_says_mild(ref, ctx, reason):
    out = assess(ctx, ref, ai("mild"))
    assert out["severity"] == "severe"
    assert any(reason in r for r in out["severe_reasons"])


def test_ai_controlled_bp_cannot_override_high_flags(ref):
    ctx = context(visits=[visit("2026-10-20", diagnosis="HTN", bp="160/100")],
                  flags=[flag("BP_SYS_HIGH", "HIGH", "2026-10-20")])
    ai_says = [Finding("bp_any", "ai", "visit 2026-10-20, diagnosis", "HTN")]  # what _check makes of bp_controlled
    out = assess(ctx, ref, ai("mild"), ai_says)
    assert "high_bp" in out["codes"] and "bp_controlled" not in out["codes"]


# ── BP and sugar: the clinic's flags decide (decided 2026-10-23) ────────────

@pytest.mark.parametrize("flags, expected", [
    ([flag("BP_SYS_HIGH", "HIGH", "2026-10-20")], "high_bp"),                  # latest reading high
    ([flag("BP_DIA_CRITICAL", "CRITICAL", "2026-08-01")], "high_bp"),          # critical in the last 5 visits
    ([flag("BP_SYS_ELEVATED", "ELEVATED", "2026-10-20")], "bp_controlled"),    # elevated doesn't count
    ([flag("BP_SYS_LOW", "LOW", "2026-10-20")], "bp_controlled"),              # low doesn't count
    ([flag("BP_SYS_HIGH", "HIGH", "2026-08-01")], "bp_controlled"),            # high, but not the latest reading
    ([], "bp_controlled"),
])
def test_bp_control_follows_the_flags(ref, flags, expected):
    ctx = context(visits=[visit("2026-10-20", diagnosis="HTN", bp="130/80"),
                          visit("2026-08-01", bp="150/95")], flags=flags)
    out = assess(ctx, ref)
    assert expected in out["codes"]
    assert (out["severity"] == "severe") == (expected == "high_bp")


def test_bp_with_no_reading_counts_as_controlled(ref):
    out = assess(context(visits=[visit("2026-10-20", diagnosis="HTN")]), ref)
    assert "bp_controlled" in out["codes"]


@pytest.mark.parametrize("flags, expected", [
    ([flag("SUGAR_MG_DL_HIGH", "HIGH", "2026-10-20")], "diabetes"),
    ([flag("FASTING_SUGAR_MG_DL_CRITICAL", "CRITICAL", "2026-08-01")], "diabetes"),
    ([flag("SUGAR_MG_DL_ELEVATED", "ELEVATED", "2026-10-20")], "diabetes_controlled"),
    ([flag("SUGAR_MG_DL_LOW", "LOW", "2026-10-20")], "diabetes_controlled"),
])
def test_sugar_control_follows_the_flags(ref, flags, expected):
    ctx = context(visits=[visit("2026-10-20", diagnosis="T2DM", sugar_mg_dl=180),
                          visit("2026-08-01", fasting_sugar_mg_dl=300)], flags=flags)
    assert expected in assess(ctx, ref)["codes"]


# ── Warning complaints ──────────────────────────────────────────────────────

def test_warning_complaint_counts_within_6_months_only(ref):
    recent = rule_findings(context(visits=[visit("2026-06-01", complaint="CHEST PAIN on walking")]), ref, TODAY)
    old = rule_findings(context(visits=[visit("2026-03-01", complaint="chest pain")]), ref, TODAY)
    assert [w["label"] for w in recent.warnings] == ["Chest pain"]
    assert old.warnings == []


def test_warning_complaint_matches_whole_words_only(ref):
    out = rule_findings(context(visits=[visit("2026-10-20", complaint="chestpain and knee pain")]), ref, TODAY)
    assert out.warnings == []
    assert [f.code for f in out.findings] == ["arthritis_knee"] and out.findings[0].complaint_only


def test_old_complaint_is_not_a_condition_but_old_diagnosis_is(ref):
    out = rule_findings(context(visits=[visit("2025-01-10", complaint="knee pain", diagnosis="oa knee")]), ref, TODAY)
    assert [(f.code, f.complaint_only) for f in out.findings] == [("arthritis_knee", False)]


# ── The AI's findings are checked against the record ────────────────────────

RECORD = {"visits": [{"date": "2026-10-20", "diagnosis_provisional": "OA knee, HTN", "complaint": "Knee pain"}]}


def check(*findings, severity="mild"):
    answer = AIAssessment(conditions=[AIFinding(code=c, quote=q, where=w) for c, q, w in findings],
                          problem="knee pain", body_area="knee", severity=severity)
    return answer


def test_ai_quote_not_in_the_record_is_dropped(ref):
    kept, dropped, _ = _check(check(("arthritis_knee", "severe OA both knees", "visit 2026-10-20, diagnosis")),
                              ref, RECORD)
    assert kept == [] and dropped[0]["why"] == "quote not found in the record"


def test_ai_code_outside_the_list_is_dropped(ref):
    kept, dropped, _ = _check(check(("knee_oa", "OA knee", "visit 2026-10-20, diagnosis"),
                                    ("none", "OA knee", "visit 2026-10-20, diagnosis")), ref, RECORD)
    assert kept == [] and {d["why"] for d in dropped} == {"not a code in the reference list"}


def test_ai_quote_is_matched_ignoring_case_and_punctuation(ref):
    kept, dropped, _ = _check(check(("arthritis_knee", "oa knee", "visit 2026-10-20, diagnosis"),
                                    ("arthritis_knee", "knee pain", "visit 2026-10-20, complaint")), ref, RECORD)
    assert [(f.code, f.complaint_only) for f in kept] == [("arthritis_knee", False), ("arthritis_knee", True)]
    assert dropped == []


def test_ai_not_listed_becomes_a_concern_not_a_condition(ref):
    kept, _, concerns = _check(check(("other_unlisted", "Knee pain", "visit 2026-10-20, complaint")), ref, RECORD)
    assert kept == [] and "Knee pain" in concerns[0]


def test_ai_high_bp_needs_the_record_to_say_uncontrolled(ref):
    kept, _, _ = _check(check(("high_bp", "HTN", "visit 2026-10-20, diagnosis")), ref, RECORD)
    assert kept[0].code == "bp_any"  # the flags decide
    record = {"visits": [{"date": "2026-10-20", "diagnosis_provisional": "Uncontrolled HTN"}]}
    kept, _, _ = _check(check(("high_bp", "Uncontrolled HTN", "visit 2026-10-20, diagnosis")), ref, record)
    assert kept[0].code == "high_bp"


# ── Randomized: no AI answer ever lowers the rules' result ──────────────────

def test_no_ai_answer_lowers_severity_or_removes_a_condition(ref):
    rng = random.Random(8)
    codes = [c for c in ref.conditions if c != "none"]
    flag_pool = [flag("BP_SYS_HIGH", "HIGH", "2026-10-20"), flag("BP_SYS_ELEVATED", "ELEVATED", "2026-10-20"),
                 flag("SUGAR_MG_DL_HIGH", "HIGH", "2026-10-20"), flag("SPO2_CRITICAL", "CRITICAL", "2026-10-20"),
                 flag("BP_DIA_CRITICAL", "CRITICAL", "2026-09-01")]
    complaints = [None, "knee pain", "chest pain", "dizziness", "fever"]
    for _ in range(500):
        ctx = context(visits=[visit("2026-10-20", complaint=rng.choice(complaints), diagnosis=rng.choice(
                          [None, "HTN", "T2DM", "OA knee", "HTN, T2DM"]), bp="140/90", sugar_mg_dl=150)],
                      flags=rng.sample(flag_pool, rng.randint(0, 3)),
                      emergencies=[{"date": "2026-10-01"}] if rng.random() < 0.1 else [])
        rule_codes = rng.sample(codes, rng.randint(0, 3))

        def rules():  # finalize changes findings in place: a fresh copy per call
            r = rule_findings(ctx, ref, TODAY)
            r.findings += [Finding(c, "rules", "visit 2026-10-20, diagnosis", c) for c in rule_codes]
            return r

        baseline = finalize(ctx, ref, rules(), ai("mild"), [])
        answer = ai(rng.choice(list(RANK)))
        ai_codes = rng.sample(codes + ["bp_any", "diabetes_any"], rng.randint(0, 3))
        out = finalize(ctx, ref, rules(), answer,
                       [Finding(c, "ai", "visit 2026-10-20, diagnosis", "x") for c in ai_codes])
        assert RANK[out["severity"]] >= RANK[baseline["severity"]]
        assert set(baseline["severe_reasons"]) <= set(out["severe_reasons"])
        # A condition the rules found stays, or only gets stricter (controlled -> not controlled).
        stricter = {"bp_controlled": "high_bp", "diabetes_controlled": "diabetes"}
        for code in set(baseline["codes"]) - {"none"}:
            assert code in out["codes"] or stricter.get(code) in out["codes"]
        if any(ref.conditions[c]["bucket"] == "refer" for c in out["codes"] if c != "none"):
            assert out["severity"] == "severe"
