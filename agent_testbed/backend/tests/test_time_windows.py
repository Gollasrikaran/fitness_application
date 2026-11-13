"""Time windows (data/time_windows.csv, 2026-11-13) and rules over every visit.

- The rules read every visit (`visits_all`, the API's whole timeline); the AI
  still reads the latest 10.
- A finding counts only inside its window: e.g. a fresh injury 90 days,
  pregnancy 365, complaints about 6 months; a condition with no row counts
  however old. What is left out is listed for the doctor."""
from datetime import date

import pytest

from agent.assess import AIAssessment, AIFinding, _check
from agent.conditions import load_reference, rule_findings
from agent.routing import finalize
from app import clinic_api
from store.models import ConditionAlias, WarningComplaint
from store.seed import _from_csv, time_windows

TODAY = date(2026, 11, 13)


@pytest.fixture
def ref(db):
    ref = load_reference(db)
    ref.aliases = [ConditionAlias(source="text", phrase="knee injury", code="acute_injury"),
                   ConditionAlias(source="text", phrase="pregnancy", code="pregnancy"),
                   ConditionAlias(source="text", phrase="oa knee", code="arthritis_knee"),
                   ConditionAlias(source="text", phrase="knee pain", code="arthritis_knee")]
    ref.warnings = [WarningComplaint(phrase="tingling", label="Numbness or tingling")]
    ref.windows = {(w["what"], w["counts_from"]): w["days"] for w in time_windows(_from_csv()[0])}
    return ref


def context(visits=(), visits_all=None):
    ctx = {"visits": list(visits), "vital_flags": [], "alerts": {"emergencies": []},
           "conditions": {"doctor_recorded": [], "long_term_conditions": [], "health_history": []},
           "body": {"bmi": None}, "patient": {"age": 50}}
    if visits_all is not None:
        ctx["visits_all"] = list(visits_all)
    return ctx


def visit(day, complaint=None, diagnosis=None):
    return {"date": day, "complaint": complaint, "diagnosis_provisional": diagnosis}


def codes(ref, ctx):
    return {f.code for f in rule_findings(ctx, ref, TODAY).findings}


# ── The CSV ─────────────────────────────────────────────────────────────────

def test_csv_values():
    # Diagnoses and complaints; the reading rows are checked in test_reading_rules.py.
    w = {(r["what"], r["counts_from"]): r["days"] for r in time_windows(_from_csv()[0]) if r["counts_from"] != "reading"}
    assert w == {("acute_injury", "diagnosis"): 90, ("recent_surgery", "diagnosis"): 90,
                 ("pregnancy", "diagnosis"): 365, ("sprain_strain", "diagnosis"): 90,
                 ("any", "complaint"): 183, ("warning", "complaint"): 183}


# ── Diagnoses ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("day, counts", [("2026-10-01", True), ("2026-08-15", True), ("2026-08-14", False),
                                         ("2025-01-01", False)])
def test_injury_counts_for_90_days(ref, day, counts):
    out = rule_findings(context([visit(day, diagnosis="Left knee injury")]), ref, TODAY)
    assert ("acute_injury" in {f.code for f in out.findings}) == counts
    assert bool(out.expired) == (not counts)


@pytest.mark.parametrize("day, counts", [("2026-01-01", True), ("2025-11-01", False)])
def test_pregnancy_counts_for_a_year(ref, day, counts):
    assert ("pregnancy" in codes(ref, context([visit(day, diagnosis="26 wks pregnancy")]))) == counts


def test_a_condition_with_no_window_counts_however_old(ref):
    assert "arthritis_knee" in codes(ref, context([visit("2023-05-01", diagnosis="Bilateral OA knee")]))


def test_a_diagnosis_with_no_date_still_counts(ref):
    assert "acute_injury" in codes(ref, context([visit(None, diagnosis="Left knee injury")]))


def test_no_windows_in_the_table_means_as_before(db):
    ref = load_reference(db)  # the test database has no time windows
    ref.aliases = [ConditionAlias(source="text", phrase="knee injury", code="acute_injury")]
    ref.warnings = []
    assert "acute_injury" in codes(ref, context([visit("2024-01-01", diagnosis="knee injury")]))


# ── Complaints ──────────────────────────────────────────────────────────────

def test_complaint_window_is_never_longer_than_the_diagnosis_window(ref):
    # 120 days old: inside the 183-day complaint window, outside the injury's 90.
    out = codes(ref, context([visit("2026-07-16", complaint="knee injury after a fall, knee pain")]))
    assert "acute_injury" not in out and "arthritis_knee" in out


# ── Every visit, not only the latest 10 ─────────────────────────────────────

def test_rules_read_visits_beyond_the_latest_10(ref):
    """0e9a6d9b (2026-11-13): tingling at visits 17 and 19 of 22 was missed."""
    latest = [visit("2026-10-06", complaint="Both knee pain")] * 10
    older = [visit("2026-06-30", complaint="tingling sensation in both hands")]
    out = rule_findings(context(latest, latest + older), ref, TODAY)
    assert [w["label"] for w in out.warnings] == ["Numbness or tingling"]


def test_warning_older_than_its_window_is_left_out(ref):
    out = rule_findings(context([], [visit("2026-04-01", complaint="tingling in legs")]), ref, TODAY)
    assert out.warnings == []


def test_api_record_has_every_timeline_visit():
    blocks = "".join(f"DATE: 2026-{m:02d}-01\n  VISIT ID: v{m}\n  Chief Complaint (database): knee pain {m}\n"
                     for m in range(12, 0, -1))
    summary = {"patient_id": "p", "age_years": 60, "sex": "FEMALE", "visits": [], "vitals": [],
               "health_history": {}, "long_term_conditions": []}
    ctx = clinic_api.build_context(summary, blocks, {}, TODAY)
    assert len(ctx["visits"]) == 10 and len(ctx["visits_all"]) == 12
    assert ctx["visits_all"][-1] == {"date": "2026-01-01", "complaint": "knee pain 1"}


# ── The AI's findings and what the doctor sees ──────────────────────────────

def ai_says(where):
    return AIAssessment(conditions=[AIFinding(code="acute_injury", quote="Left knee injury", where=where)],
                        problem="knee", body_area="knee", severity="moderate")


RECORD = {"visits": [{"date": "2026-07-01", "diagnosis_provisional": "Left knee injury"}]}


@pytest.mark.parametrize("where, kept", [("visit 2026-07-01, diagnosis", False), ("visit 2026-10-01, diagnosis", True),
                                         ("diagnosis", True)])
def test_ai_finding_outside_its_window_is_dropped(ref, where, kept):
    found, dropped, _ = _check(ai_says(where), ref, RECORD, TODAY)
    assert bool(found) == kept
    assert bool(dropped) == (not kept) and (kept or "time window" in dropped[0]["why"])


def test_doctor_sees_what_was_left_out_as_too_old(ref):
    ctx = context([visit("2026-07-01", diagnosis="Left knee injury")])
    rules = rule_findings(ctx, ref, TODAY)
    out = finalize(ctx, ref, rules, {"severity": "mild", "problem": "x"}, [])
    assert "acute_injury" not in out["codes"]
    assert any(c.startswith("Not counted, too old: Fresh injury") for c in out["concerns"])
