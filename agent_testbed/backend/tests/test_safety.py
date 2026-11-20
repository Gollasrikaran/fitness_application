"""Phase 8 safety tests (agent.routing, agent.conditions, agent.assess._check):
whatever the AI says, the rules' severity stands; BP control follows the
average reading (fix 03) and sugar control the clinic's flags; warning
complaints; the AI quote checks."""
import random
from datetime import date

import pytest

from agent.assess import AIAssessment, AIFinding, _check
from agent.conditions import Finding, RuleResult, load_reference, rule_findings
from agent.routing import finalize
from store import plans
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


# ── BP: the average of the latest readings decides (fix 03, 2026-11-20) ─────
# Below 140/90 under control; 140-159/90-99 above target (an AI draft with
# the 140/90 limits); 160/100 or above, or a critical flag: a doctor. One
# reading only: control not known. HIGH flags no longer decide on their own.
# Sugar still follows the clinic's flags (decided 2026-10-23).

def bp_visits(*readings):
    """("2026-10-20", "130/80"), ... -> visits, the first with the HTN diagnosis."""
    return [visit(day, diagnosis="HTN" if i == 0 else None, bp=bp) for i, (day, bp) in enumerate(readings)]


@pytest.mark.parametrize("readings, flags, code, name", [
    ([("2026-10-20", "130/80"), ("2026-09-20", "120/78")], [], "bp_controlled", "BP under control"),
    ([("2026-10-10", "133/87"), ("2026-09-17", "130/90"), ("2026-08-29", "150/93")], [],  # 6959e408
     "bp_controlled", "BP above target (average 138/90 of 3 readings)"),
    ([("2026-10-20", "170/105"), ("2026-09-20", "160/100")], [], "high_bp", None),
    ([("2026-10-20", "131/90")], [], "bp_controlled", "BP, control not known (one reading in 90 days: 131/90)"),
    ([("2026-10-20", "130/80"), ("2026-09-20", "120/78")], [flag("BP_DIA_CRITICAL", "CRITICAL", "2026-08-01")],
     "high_bp", None),                                                              # critical in the last 5 visits
    ([("2026-10-20", "141/80"), ("2026-09-20", "120/78")], [flag("BP_SYS_HIGH", "HIGH", "2026-10-20")],
     "bp_controlled", "BP under control"),                                          # a HIGH flag alone: the average decides
    ([("2026-10-20", "120/80"), ("2026-10-01", "120/80"), ("2026-09-20", "120/80"), ("2026-09-01", "200/120")], [],
     "bp_controlled", "BP under control"),                                          # only the latest 3 dates
])
def test_bp_control_follows_the_average(ref, readings, flags, code, name):
    out = assess(context(visits=bp_visits(*readings), flags=flags), ref)
    assert code in out["codes"]
    assert (out["severity"] == "severe") == (code == "high_bp")
    if name:
        assert next(c for c in out["conditions"] if c["code"] == code)["name"] == name


def test_two_records_on_one_day_count_once_in_the_average(ref):
    ctx = context(visits=[visit("2026-10-20", diagnosis="HTN", bp="150/95"), visit("2026-10-20", bp="150/95"),
                          visit("2026-09-20", bp="120/80")])
    bp = next(c for c in assess(ctx, ref)["conditions"] if c["code"] == "bp_controlled")
    assert bp["name"] == "BP under control"  # 135/88 from 2 dates, not 140/90 from 3 records
    assert any("average of 2 readings" in e for e in bp["evidence"])


def test_above_target_bp_gets_the_140_90_limits(db):
    readings = {"bp": plans.latest_bp([{"date": "2026-10-10", "bp": "133/87"}, {"date": "2026-09-17", "bp": "130/90"},
                                       {"date": "2026-08-29", "bp": "150/93"}], date(2026, 11, 20))}
    assert readings["bp"] == {"sys": 138.0, "dia": 90.0, "date": "2026-10-10", "count": 3, "from": "2026-08-29",
                              "readings": ["133/87 on 2026-10-10", "130/90 on 2026-09-17", "150/93 on 2026-08-29"]}
    allowed, lines = plans.candidates(db, ["bp_controlled"], 57, 25, readings)
    kinds = {e["activity_type"] for e in allowed}
    assert not kinds & {"wall_sit", "neck_isometric", "running"} and "walk" in kinds
    assert any("138/90 (average of 3 readings, 2026-08-29 to 2026-10-10)" in line for line in lines)


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
        ai_codes = rng.sample(codes + ["bp_any", "diabetes_any", "asthma_any"], rng.randint(0, 3))
        out = finalize(ctx, ref, rules(), answer,
                       [Finding(c, "ai", "visit 2026-10-20, diagnosis", "x") for c in ai_codes])
        assert RANK[out["severity"]] >= RANK[baseline["severity"]]
        assert set(baseline["severe_reasons"]) <= set(out["severe_reasons"])
        # A condition the rules found stays, or only gets stricter (controlled -> not controlled;
        # underactive thyroid -> overactive, 2026-11-18).
        stricter = {"bp_controlled": "high_bp", "diabetes_controlled": "diabetes",
                    "asthma_controlled": "asthma_uncontrolled", "hypothyroid": "hyperthyroid"}
        for code in set(baseline["codes"]) - {"none"}:
            assert code in out["codes"] or stricter.get(code) in out["codes"]
        if any(ref.conditions[c]["bucket"] == "refer" for c in out["codes"] if c != "none"):
            assert out["severity"] == "severe"


# ── No reading: control not known (1123000d, 2026-11-05) ─────────────────────

def test_diabetes_with_no_sugar_reading_says_control_not_known(ref):
    ctx = context(visits=[visit("2026-10-20", diagnosis="T2DM", bp="113/76")])
    out = assess(ctx, ref)
    dm = next(c for c in out["conditions"] if c["code"] == "diabetes_controlled")
    assert dm["name"] == "Diabetes, control not known (no recent sugar reading)"
    assert any("not known" in e for e in dm["evidence"])
    assert out["severity"] != "severe"  # the safety decision is unchanged


def test_diabetes_with_an_unflagged_reading_is_still_under_control(ref):
    ctx = context(visits=[visit("2026-10-20", diagnosis="T2DM", sugar_mg_dl=120)])
    dm = next(c for c in assess(ctx, ref)["conditions"] if c["code"] == "diabetes_controlled")
    assert "not known" not in dm["name"]


def test_bp_with_no_reading_says_control_not_known(ref):
    bp = next(c for c in assess(context(visits=[visit("2026-10-20", diagnosis="HTN")]), ref)["conditions"]
              if c["code"] == "bp_controlled")
    assert bp["name"] == "BP, control not known (no recent BP reading)"


# ── Dizziness stops a draft only for higher-risk patients (option 2, 2026-11-05) ──

def aged(ctx, age):
    return {**ctx, "patient": {"age": age}}


def test_dizziness_in_a_young_patient_with_no_risk_is_a_concern_not_a_stop(ref):
    out = assess(aged(context(visits=[visit("2026-10-20", complaint="Dizziness, acidity")]), 35), ref)
    assert out["severity"] != "severe" and not out["severe_reasons"]
    assert len(out["concerns"]) == 1 and out["concerns"][0].startswith("Dizziness in the complaint on 2026-10-20")


@pytest.mark.parametrize("age, diagnosis", [(60, None), (80, None), (35, "HTN"), (35, "T2DM")])
def test_dizziness_still_stops_at_60_or_with_bp_or_diabetes(ref, age, diagnosis):
    ctx = aged(context(visits=[visit("2026-10-20", complaint="dizziness", diagnosis=diagnosis)]), age)
    out = assess(ctx, ref)
    assert out["severity"] == "severe" and any(r.startswith("Dizziness") for r in out["severe_reasons"])
    assert not out["concerns"]


def test_dizziness_still_stops_with_a_heart_condition(ref):
    ctx = aged(context(visits=[visit("2026-10-20", complaint="dizziness")]), 35)
    out = assess(ctx, ref, ai_findings=[Finding("heart_condition", "ai", "visit 2026-10-20, diagnosis", "x")])
    assert any(r.startswith("Dizziness") for r in out["severe_reasons"])


def test_other_warning_complaints_stop_whatever_the_age(ref):
    out = assess(aged(context(visits=[visit("2026-10-20", complaint="chest pain")]), 25), ref)
    assert out["severity"] == "severe" and not out["concerns"]


def test_no_age_and_no_risk_codes_means_a_concern(ref):
    # The database source always has an age; without one, the conditions alone decide.
    out = assess(context(visits=[visit("2026-10-20", complaint="dizziness")]), ref)
    assert not any(r.startswith("Dizziness") for r in out["severe_reasons"]) and out["concerns"]


# ── Kidney disease written in a diagnosis (7673431d, 2026-11-13) ────────────

@pytest.mark.parametrize("diagnosis", ["CKD/ HTN", "HT with CKD", "Chronic kidney disease stage 3",
                                       "kidney disease", "Acute renal failure"])
def test_kidney_disease_in_a_diagnosis_needs_a_doctor(db, diagnosis):
    """The real alias file: CKD only matched the recorded-condition name before."""
    from store.seed import _aliases, _from_csv
    real = load_reference(db)
    real.aliases = [ConditionAlias(**a) for a in _aliases(_from_csv()[0])]
    real.warnings = []
    out = assess(context(visits=[visit("2026-10-08", diagnosis=diagnosis)]), real)
    assert "other_unlisted" in out["codes"] and out["severity"] == "severe"


def test_kidney_stone_is_not_kidney_disease(db):
    from store.seed import _aliases, _from_csv
    real = load_reference(db)
    real.aliases = [ConditionAlias(**a) for a in _aliases(_from_csv()[0])]
    real.warnings = []
    out = rule_findings(context(visits=[visit("2026-10-08", diagnosis="Renal calculi, kidney stone")]), real, TODAY)
    assert "other_unlisted" not in {f.code for f in out.findings}


# ── The AI's free text doesn't claim control (fix 2026-11-16) ──────────────

@pytest.mark.parametrize("text, out", [
    # bd8b445c: the rules could not know the sugar control, the AI still said "controlled"
    ("The patient has chronic back pain and spondylosis, along with obesity and controlled diabetes and hypertension.",
     "The patient has chronic back pain and spondylosis, along with obesity and diabetes and hypertension."),
    ("Knee pain with well-controlled hypertension", "Knee pain with hypertension"),
    ("Uncontrolled DM and knee OA", "DM and knee OA"),
    ("Back pain; BP is under control.", "Back pain; BP."),
    ("Diabetes not under control, knee pain", "Diabetes, knee pain"),
    ("Knee osteoarthritis, obesity", "Knee osteoarthritis, obesity")])
def test_ai_text_never_claims_control(text, out):
    from agent.assess import no_control_claims
    assert no_control_claims(text) == out


# ── "Under control" uses the reading's window (decided 2026-11-16) ─────────
# Old good news doesn't count; old bad news still does.

from datetime import date as _date

from agent.routing import _SUGAR_FLAG, _SUGAR_KEYS, _bp_control, _uncontrolled

_TODAY = _date(2026, 11, 16)


def test_an_old_normal_sugar_is_control_not_known():
    """016e4c77: sugar 128.4 on 2026-08-06 (102 days), no flag."""
    visits = [{"date": "2026-08-06", "vitals": {"nonfasting_sugar_mg_dl": 128.4}}]
    bad, why = _uncontrolled(visits, [], _SUGAR_FLAG, _SUGAR_KEYS, "sugar", _TODAY, 90)
    assert bad is None
    assert why == ("latest sugar reading (2026-08-06, 102 days ago: older than its 90-day window) "
                   "not flagged high, so whether it is under control is not known")


def bp_ctx(*readings):
    return {"visits": [{"date": day, "vitals": {"bp": bp}} for day, bp in readings], "vital_flags": []}


def test_an_old_very_high_bp_still_means_not_under_control():
    bad, why, _ = _bp_control(bp_ctx(("2026-07-10", "172/98")), None, _TODAY)
    assert bad is True and "older than 90 days, at or above 160/100" in why


def test_an_old_bp_below_160_100_is_control_not_known():
    bad, why, name = _bp_control(bp_ctx(("2026-07-10", "150/95")), None, _TODAY)
    assert bad is None and "no BP reading in the last 90 days" in why
    assert name is None  # shown as "BP, control not known (no recent BP reading)"


def test_recent_normal_readings_are_under_control():
    bad, why, name = _bp_control(bp_ctx(("2026-10-01", "135/76"), ("2026-09-01", "125/80")), None, _TODAY)
    assert bad is False and name is None and "below 140/90" in why


def test_finalize_shows_an_old_normal_reading_as_control_not_known(db):
    from agent.conditions import Finding, RuleResult, load_reference
    from agent.routing import finalize
    rules = RuleResult(findings=[Finding("diabetes_any", "rules", "visit 2026-08-06, diagnosis", "T2dm")],
                       unmapped=[], warnings=[])
    ctx = {"visits": [{"date": "2026-08-06", "vitals": {"nonfasting_sugar_mg_dl": 128.4}}], "vital_flags": [],
           "conditions": {"doctor_recorded": []}, "alerts": {"emergencies": []}, "patient": {"age": 40}, "body": {}}
    [dm] = finalize(ctx, load_reference(db), rules, None, [], _TODAY)["conditions"]
    assert dm["code"] == "diabetes_controlled"  # the same exercise rules as before
    assert dm["name"] == "Diabetes, control not known (no recent sugar reading)"
