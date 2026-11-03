"""Patient records from the Patient Intelligence API (app/clinic_api.py):
the API's text turned into the same record shape app/clinic.py returns, so
the agent and the rules work on it unchanged. Made-up responses in the API's
real format (PATIENT_API_FINDINGS.md); no network."""
from datetime import date

import pytest

from agent.conditions import load_reference, rule_findings
from agent.draft import eligibility_note, patient_profile
from agent.routing import finalize
from app import clinic_api, patient_api
from store import plans
from store.models import ConditionAlias, WarningComplaint
from store.seed import _aliases, _from_csv, _rows

TODAY = date(2026, 11, 3)

TIMELINE = """PATIENT ID: p1
TOTAL VISITS RECORDED: 3
DATE: 2026-10-20
  2 separate visits recorded on this date
  Visit A of 2
  VISIT ID: v3
  Chief Complaint (database): K/C/O asthma, breathlessness, cough,
  Provisional Diagnosis (database): Htn, bronchial asthma
  Confirmed Diagnosis (database): Not Documented
  Prescription Instructions (database): Avoid dust
  Vitals (database): BP: 150/94 mmHg, Pulse: 104 bpm, SpO₂: 95%
  Visit B of 2
  VISIT ID: v2
  Chief Complaint (database): knee pain
  Provisional Diagnosis (database): Not Documented
  Confirmed Diagnosis (database): OA knee
DATE: 2026-03-02
  VISIT ID: v1
  Chief Complaint (database): fever
  Provisional Diagnosis (database): Acute febrile illness
"""

SUMMARY = {
    "patient_id": "p1", "age_years": 61, "sex": "FEMALE",
    "health_history": {"asthma": {"present": True, "notes": ""}, "hypertension": {"present": True, "notes": ""},
                       "diabetes": {"present": False, "notes": ""}, "smoking": {"present": False, "qty": ""},
                       "other_notes": ""},
    "long_term_conditions": [{"name": "Hypertension", "severity": None, "status": "ACTIVE", "diagnosed_at": None}],
    "visits": [{"visit_id": "v3", "visit_date": "2026-10-20", "doctor_id": "d1", "is_emergency": False,
                "is_referral_recommended": False},
               {"visit_id": "v2", "visit_date": "2026-10-20", "doctor_id": "d1", "is_emergency": False,
                "is_referral_recommended": True, "referral_specialist_name": "Ortho", "referral_treatment_name": "knee"},
               {"visit_id": "v1", "visit_date": "2026-03-02", "doctor_id": "d2", "is_emergency": True}],
    "patient_type": "Cardiovascular", "exercise_suitable": False,
    "ongoing_medicines": ["Inh Foracort", "Amlodipine 5"],
    "vitals": [{"visit_id": "v3", "visit_date": "2026-10-20", "readings": [
                   {"label": "BP", "value": "150/94 mmHg"}, {"label": "Pulse", "value": "104 bpm"},
                   {"label": "SpO₂", "value": "95%"}, {"label": "Weight", "value": "57.6 kg"},
                   {"label": "Height", "value": "157 cm"}, {"label": "Temperature", "value": "None"}]},
               {"visit_id": "v1", "visit_date": "2026-03-02", "readings": [
                   {"label": "Fasting Sugar", "value": "118 mg/dL"}, {"label": "BP", "value": "140/ mmHg"}]}],
    "vital_flags": [{"visit_id": "v3", "date": "2026-10-20", "metric": "bp_sys", "code": "BP_SYS_HIGH",
                     "severity": "ABNORMAL", "value": 150}],
    "clinical_snapshot": {"encounters": 3, "span": "2026-03-02 to 2026-10-20",
                          "flags": [{"level": "medium", "title": "Recurring respiratory symptoms", "evidence": "x"},
                                    {"level": "info", "title": "BMI 23", "evidence": "y"}]},
}

# The keys app/clinic.py's patient_context() returns: the API record must match them.
DB_KEYS = {"patient", "body", "conditions", "history_other", "vitals_recent", "vital_flags", "visits", "medicines",
           "care", "alerts", "as_of"}


@pytest.fixture
def ctx():
    return clinic_api.build_context(SUMMARY, TIMELINE, {"d1": "Asha Rao", "d2": "Ravi Kumar"}, TODAY)


# ── Parsing ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label, value, out", [
    ("BP", "130/80 mmHg", ("bp", "130/80")), ("BP", "140/ mmHg", None), ("BP", "None mmHg", None),
    ("SpO₂", "96%", ("spo2", 96.0)), ("Pulse", "88.5 bpm", ("pulse", 88.5)), ("Weight", "57.6 kg", ("weight_kg", 57.6)),
    ("Fasting Sugar", "118 mg/dL", ("fasting_sugar_mg_dl", 118.0)), ("Temperature", "None", None),
    ("Something new", "5", None)])
def test_readings_are_parsed_from_text(label, value, out):
    assert clinic_api.parse_reading(label, value) == out


def test_timeline_gives_one_entry_per_visit_even_on_the_same_date():
    visits = clinic_api.parse_timeline(TIMELINE)
    assert [(v["date"], v["visit_id"]) for v in visits] == [("2026-10-20", "v3"), ("2026-10-20", "v2"),
                                                          ("2026-03-02", "v1")]
    assert visits[0]["complaint"] == "K/C/O asthma, breathlessness, cough"
    assert visits[0]["provisional"] == "Htn, bronchial asthma" and visits[0]["confirmed"] is None
    assert visits[1]["confirmed"] == "OA knee" and visits[0]["instructions"] == "Avoid dust"


def test_timeline_without_visit_ids_still_parses():
    visits = clinic_api.parse_timeline("DATE: 2026-01-05\n  Chief Complaint (database): back pain\n")
    assert visits == [{"date": "2026-01-05", "visit_id": None, "complaint": "back pain"}]


# A real visit's shape (2026-11-03): instructions over three lines, the same
# lab report uploaded twice, and medicine lines that aren't labs.
LAB_TIMELINE = """PATIENT ID: p9
============================================================

DATE: 2026-06-06
--------------------------------------------------
  VISIT ID: v9
  Chief Complaint (database): Report check,6 month heavy bleeding, abdominal pain,
  Provisional Diagnosis (database): Not Documented
  Prescription Instructions (database): DUB
Perimenopause ; Heavy bleeding
Lmp ??
  Vitals (database): Pulse: 86 bpm, SpO₂: 96%
  Medicines — Prescription (database):
    • Tab shelcal-XT, dosage 0-1-0, frequency After food, duration 60 days
  Supporting Document(s): 3 found
    --- Document 1 ---
    Lab Results (Document 1):
      • HIV: Non-reactive (Ref: ) [Normal]
      • HbA1c: 5.1 % (Ref: ≤ 5.6 % (standard adult range; report gave none)) [Unverified (check source)]
      • Fasting Blood Sugar: 7.2 mmol/L (Ref: 3.9 - 5.5 mmol/L) [High]
    --- Document 2 ---
    Lab Results (Document 2):
      • Haemoglobin: 6.5 g/dL (Ref: 12 - 17.5 g/dL (standard adult range; report gave none)) [Critical (Low)]
      • Haemoglobin: 6 g/dL (Ref: 12 - 17.5 g/dL (standard adult range; report gave none)) [Critical (Low)]
    --- Document 3 ---
    Lab Results (Document 3):
      • Haemoglobin: 6.5 g/dL (Ref: 12 - 17.5 g/dL (standard adult range; report gave none)) [Critical (Low)]
"""


def test_instructions_over_several_lines_are_kept_whole():
    visit = clinic_api.parse_timeline(LAB_TIMELINE)[0]
    assert visit["instructions"] == "DUB; Perimenopause ; Heavy bleeding; Lmp ??"
    assert visit["complaint"] == "Report check,6 month heavy bleeding, abdominal pain"


def test_lab_results_are_read_once_each_and_medicines_are_not_labs():
    labs = clinic_api.parse_timeline(LAB_TIMELINE)[0]["labs"]
    assert labs == [{"name": "HIV", "value": "Non-reactive", "status": "Normal"},
                    {"name": "HbA1c", "value": "5.1 %", "status": "Unverified (check source)"},
                    {"name": "Fasting Blood Sugar", "value": "7.2 mmol/L", "status": "High"},
                    {"name": "Haemoglobin", "value": "6.5 g/dL", "status": "Critical (Low)"},
                    {"name": "Haemoglobin", "value": "6 g/dL", "status": "Critical (Low)"}]
    # The rules get the lowest Hb; sugar in mmol/L and unverified results are left out.
    assert clinic_api.lab_readings(labs) == {"hb": 6.0}


def test_low_hb_from_a_lab_report_reaches_the_reading_rules():
    """Hb below 8 means no plan, a doctor decides (data/reading_rules.csv)."""
    summary = {"patient_id": "p9", "age_years": 29, "sex": "FEMALE",
               "visits": [{"visit_id": "v9", "visit_date": "2026-06-06", "doctor_id": "d1"}],
               "vitals": [{"visit_id": "v9", "visit_date": "2026-06-06",
                           "readings": [{"label": "Pulse", "value": "86 bpm"}]}]}
    ctx = clinic_api.build_context(summary, LAB_TIMELINE, {}, date(2026, 7, 1))
    assert ctx["visits"][0]["vitals"] == {"pulse": 86.0, "hb": 6.0}
    assert ctx["labs"][-1] == {"date": "2026-06-06", "name": "Haemoglobin", "value": "6 g/dL",
                               "status": "Critical (Low)"}
    assert plans.latest_readings(ctx["vitals_recent"], date(2026, 7, 1))["hb"] == {"value": 6.0,
                                                                                    "date": "2026-06-06"}


# ── The record ──────────────────────────────────────────────────────────────

def test_record_has_the_same_shape_as_the_database_one(ctx):
    assert set(ctx) == DB_KEYS | {"clinical_summary", "labs"}
    assert ctx["patient"] == {"id": "p1", "age": 61, "sex": "FEMALE", "language": None, "registered_on": None}
    assert set(ctx["conditions"]) == {"doctor_recorded", "health_history", "long_term_conditions", "recent_diagnoses"}
    assert set(ctx["care"]) >= {"visits", "first_visit", "last_visit", "recent_complaints", "followups",
                                "open_episodes", "open_tasks"}
    assert set(ctx["alerts"]) == {"emergencies", "referrals"}


def test_record_values(ctx):
    v3 = ctx["visits"][0]
    assert v3["doctor"] == "Asha Rao" and v3["vitals"] == {"bp": "150/94", "pulse": 104.0, "spo2": 95.0,
                                                            "weight_kg": 57.6, "height_cm": 157.0}
    assert ctx["body"] == {"weight_kg": 57.6, "height_cm": 157.0, "bmi": 23.4, "measured_on": "2026-10-20"}
    assert [h["item"] for h in ctx["conditions"]["health_history"]] == ["hypertension", "asthma"]
    assert ctx["conditions"]["doctor_recorded"][0]["name"] == "Hypertension"
    assert ctx["vital_flags"] == [{"date": "2026-10-20", "metric": "bp_sys", "code": "BP_SYS_HIGH",
                                   "severity": "ABNORMAL", "value": 150}]
    assert ctx["alerts"]["emergencies"] == [{"date": "2026-03-02", "diagnosis": "Acute febrile illness"}]
    assert ctx["alerts"]["referrals"] == [{"date": "2026-10-20", "to": "Ortho", "for": "knee"}]
    assert ctx["care"]["visits"] == 3 and ctx["care"]["first_visit"] == "2026-03-02"
    assert ctx["medicines"]["items"] == [{"name": "Inh Foracort"}, {"name": "Amlodipine 5"}]
    assert ctx["clinical_summary"] == {"exercise_suitable": False, "patient_type": "Cardiovascular",
                          "flags": [{"level": "medium", "title": "Recurring respiratory symptoms", "evidence": "x"}]}


def test_readings_rules_can_read_the_api_vitals(ctx):
    readings = plans.latest_readings(ctx["vitals_recent"], TODAY)
    assert readings["bp"] == {"sys": 150.0, "dia": 94.0, "date": "2026-10-20"}
    assert readings["spo2"]["value"] == 95.0 and readings["pulse"]["value"] == 104.0


def test_the_rules_find_conditions_in_the_api_record(db, ctx):
    ref = load_reference(db)
    ref.aliases = [ConditionAlias(**a) for a in _aliases(_from_csv()[0])]
    ref.warnings = [WarningComplaint(phrase=r["phrase"].strip().lower(), label=r["label"])
                    for r in _rows("warning_complaints.csv")]
    rules = rule_findings(ctx, ref, TODAY)
    out = finalize(ctx, ref, rules, {"severity": "mild", "problem": "x"}, [])
    # The latest BP is flagged BP_SYS_HIGH: the API's flag codes drive the BP rule as the clinic's did.
    assert {"asthma_uncontrolled", "arthritis_knee", "high_bp"} <= set(out["codes"])
    assert out["severity"] == "severe"  # breathlessness, an emergency visit, BP not under control


# ── The colleague's check: a warning, never a block (Option A, 2026-11-03) ──

def test_not_suitable_is_a_warning_line_for_the_doctor(ctx):
    note = eligibility_note(ctx)
    assert "not suitable for exercise" in note and "Cardiovascular" in note
    assert patient_profile(ctx)["eligibility_note"] == note
    assert eligibility_note({**ctx, "clinical_summary": {**ctx["clinical_summary"], "exercise_suitable": True}}) is None
    assert eligibility_note({k: v for k, v in ctx.items() if k != "clinical_summary"}) is None  # the database source


# ── The five functions, with the API faked ──────────────────────────────────

@pytest.fixture
def fake_api(monkeypatch):
    responses = {
        "/doctors": {"doctors": [{"doctor_id": "d1", "name": "Asha Rao", "patients": 2}]},
        "/doctors/d1/patients": {"patients": [{"patient_id": "p1", "visits": 3, "last_visit": "2026-10-20"},
                                              {"patient_id": "kid", "visits": 2, "last_visit": "2026-10-21"},
                                              {"patient_id": "p3", "visits": 1, "last_visit": "2026-10-22"}]},
        "/patients/p1/summary": SUMMARY,
        "/patients/kid/summary": {**SUMMARY, "patient_id": "kid", "age_years": 4},
        "/patients/p1/timeline": {"timeline": TIMELINE},
        "/patients/p1/demographics": {"patient_id": "p1", "age_years": 61, "sex": "FEMALE",
                                      "age_sex": "61 years / Female"},
        "/patients/kid/demographics": {"patient_id": "kid", "age_years": 4, "sex": "MALE", "age_sex": "4 years / Male"},
    }
    calls = []

    def get(path, **params):
        calls.append(path)
        return responses.get(path)
    monkeypatch.setattr(patient_api, "get", get)
    clinic_api._cache.clear()
    clinic_api._people.clear()
    yield calls
    clinic_api._cache.clear()
    clinic_api._people.clear()


def per_patient_calls(calls, kind):
    return [c for c in calls if c.endswith(f"/{kind}")]


def test_lists_make_no_per_patient_calls(fake_api):
    """Listing a doctor's patients is one call: never /summary, never /demographics."""
    first = clinic_api.patients("d1", "", 100, 2)
    assert [(p["id"], p["age"], p["sex"]) for p in first] == [("kid", None, None), ("p1", None, None)]
    clinic_api.patients(None, "", 100, 2)  # no doctor chosen: the busiest doctor's list
    assert per_patient_calls(fake_api, "summary") == [] and per_patient_calls(fake_api, "demographics") == []


def test_review_queue_uses_demographics_once_per_patient(fake_api):
    briefs = clinic_api.patient_briefs(["p1", "kid", "p1"])
    assert briefs == {"p1": {"id": "p1", "age": 61, "sex": "FEMALE"}, "kid": {"id": "kid", "age": 4, "sex": "MALE"}}
    clinic_api.patient_briefs(["p1", "kid"])  # remembered: no new calls
    assert per_patient_calls(fake_api, "demographics") == ["/patients/p1/demographics", "/patients/kid/demographics"]
    assert per_patient_calls(fake_api, "summary") == []
    # Now known: the list shows their age and leaves the child out, still without calls.
    assert [(p["id"], p["age"]) for p in clinic_api.patients("d1", "", 100, 2)] == [("p1", 61)]


def test_opened_patients_are_remembered_without_extra_calls(fake_api):
    clinic_api.patient_context("p1")
    clinic_api.patient_context("kid")
    assert per_patient_calls(fake_api, "summary") == ["/patients/p1/summary", "/patients/kid/summary"]
    rows = clinic_api.patients("d1", "", 100, 2)
    assert [(p["id"], p["age"], p["sex"]) for p in rows] == [("p1", 61, "FEMALE")]
    assert rows[0]["history"] == ["asthma", "hypertension"]
    assert clinic_api.patient_briefs(["p1"]) == {"p1": {"id": "p1", "age": 61, "sex": "FEMALE"}}
    assert per_patient_calls(fake_api, "demographics") == []  # already known from the record


def test_a_patients_doctors_cost_one_summary_call(fake_api):
    """Picking the patient first: their doctors come from /summary, and opening
    the patient afterwards reuses it."""
    assert clinic_api.patient_doctors("p1") == [
        {"id": "d1", "name": "Asha Rao", "visits": 2, "last_visit": "2026-10-20"},
        {"id": "d2", "name": None, "visits": 1, "last_visit": "2026-03-02"}]
    clinic_api.patient_context("p1")
    assert per_patient_calls(fake_api, "summary") == ["/patients/p1/summary"]
    assert clinic_api.patient_doctors("kid") == [] and clinic_api.patient_doctors("unknown") == []


def test_lists_leave_out_too_few_visits_and_name_doctors(fake_api):
    assert "p3" not in [p["id"] for p in clinic_api.patients("d1", "", 100, 2)]
    assert clinic_api.doctors() == [{"id": "d1", "name": "Asha Rao", "specialization": None, "patients": 2}]
    assert clinic_api.doctor_name("d1") == "Asha Rao" and clinic_api.doctor_name("zz") is None


def test_patient_context_through_the_api(fake_api):
    ctx = clinic_api.patient_context("p1")
    assert ctx["visits"][0]["doctor"] == "Asha Rao"
    assert clinic_api.patient_context("kid") is None  # adults only
    assert clinic_api.patient_context("unknown") is None
