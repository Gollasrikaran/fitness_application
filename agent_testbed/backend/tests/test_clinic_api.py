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


FOLLOWUP_TIMELINE = """PATIENT ID: p1
DATE: 2026-09-16
  VISIT ID: v2
  Chief Complaint (database): Report study
  Medicines — Prescription (database):
    • T. Metformin, dosage 0-1-0, frequency After food, duration 15 days
  Follow-up Schedule (3 scheduled | 0 completed | 1 missed):
    • 2026-10-01 | MISSED
    • 2026-11-20 | PENDING
    • 2026-10-05 | CANCELLED
DATE: 2026-09-09
  VISIT ID: v1
  Chief Complaint (database): Repor study
  Follow-up Schedule (2 scheduled | 1 completed | 1 missed):
    • 2026-09-12 | MISSED
    • 2026-09-16 | COMPLETED → TAKING_MEDICINE_ON_TIME [Taking medicine on time]
"""


def test_followups_come_from_every_visit_in_the_timeline():
    """0b84894f (AI_TESTING note 9): the screen said "0 missed" because the
    API source had no follow-ups; they are in the timeline."""
    visits = clinic_api.parse_timeline(FOLLOWUP_TIMELINE)
    assert visits[0]["followups"] == [{"date": "2026-10-01", "status": "MISSED"},
                                      {"date": "2026-11-20", "status": "PENDING"},
                                      {"date": "2026-10-05", "status": "CANCELLED"}]
    assert "labs" not in visits[0]  # a medicine bullet isn't a follow-up or a lab
    assert clinic_api.followup_counts(visits) == {"pending": 1, "next_due": "2026-11-20", "missed": 2,
                                                  "last_missed": "2026-10-01", "emergency": None}
    ctx = clinic_api.build_context({**SUMMARY, "visits": []}, FOLLOWUP_TIMELINE, {}, TODAY)
    assert ctx["care"]["followups"]["missed"] == 2


def test_no_followups_in_the_timeline_means_none_recorded(ctx):
    assert ctx["care"]["followups"] is None  # the screen says "none recorded", not "0 missed"


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
    # The real case was checked 150 days later: a lab result still counts (6 months).
    assert plans.latest_readings(ctx["vitals_recent"], date(2026, 11, 3))["hb"]["value"] == 6.0
    assert plans.latest_readings(ctx["vitals_recent"], date(2026, 11, 3))["pulse"] is None  # a vital: 90 days


# ── The record ──────────────────────────────────────────────────────────────

def test_record_has_the_same_shape_as_the_database_one(ctx):
    # visits_all: every timeline visit, for the rules (the database source falls back to `visits`).
    assert set(ctx) == DB_KEYS | {"clinical_summary", "labs", "visits_all"}
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
    # No prescription lines in the timeline: none, not /summary's ongoing_medicines.
    assert ctx["medicines"]["items"] == [] and ctx["medicines"]["from"] is None
    assert ctx["clinical_summary"] == {"exercise_suitable": False, "patient_type": "Cardiovascular",
                          "exercise_reason": None, "flags": [{"level": "medium", "title": "Recurring respiratory symptoms", "evidence": "x",
                                                              "kind": None, "time": None, "as_of": None, "undated": None}]}


# bd8b445c (2026-11-16): /summary's ongoing_medicines listed 28 medicines,
# Amlodipine and NSAIDs long stopped among them; the latest prescription had 7.
MEDICINE_TIMELINE = """PATIENT ID: p5
DATE: 2026-10-01
  VISIT ID: v4
  Chief Complaint (database): K/C/o-HTN,DM, report check
  Medicines — Prescription (database):
    • Glimperide, dosage 1-0-0, frequency Before food, duration 10 days
    • Telmisartan, dosage 1-0-0, frequency After food, duration 10 days
  Supporting Document: NONE — no document was uploaded/extracted for this visit.
  Follow-up Schedule (1 scheduled | 0 completed | 1 missed):
    • 2026-10-11 | MISSED
DATE: 2026-09-28
  Visit A of 2
  VISIT ID: v3
  Chief Complaint (database): general weakness
  Medicines — Prescription (database):
    • Amlodipine, dosage 1-0-0, frequency After food, duration 10 days
    • Telmisartan, dosage 1-0-0
  Visit B of 2
  VISIT ID: v2
  Chief Complaint (database): neck pain
  Medicines — Prescription (database): none recorded
DATE: 2026-08-27
  VISIT ID: v1
  Medicines — Prescription (database):
    • Glimipride, dosage 1-0-1
    • low salt diet, dosage 1-0-1, frequency After food
    • Metformin, dosage 1-0-1, duration 30 days
"""


@pytest.mark.parametrize("line, out", [
    ("    • Tab Tendocare, dosage 0-1-0, frequency After food, duration 5 days",
     {"name": "Tab Tendocare", "dosage": "0-1-0", "frequency": "After food", "duration": "5 days"}),
    ("      • Metformin, dosage 1-0-1, duration 30 days", {"name": "Metformin", "dosage": "1-0-1", "duration": "30 days"}),
    ("      • Glimipride, dosage 1-0-1", {"name": "Glimipride", "dosage": "1-0-1"}),
    ("      • Calcium Carbonate Tab + vit D3 1.25 gm, dosage 0-1-0",
     {"name": "Calcium Carbonate Tab + vit D3 1.25 gm", "dosage": "0-1-0"}),
    ("      • Pan", {"name": "Pan"}),
    ("  Chief Complaint (database): fever", None)])
def test_medicine_lines_are_parsed(line, out):
    assert clinic_api.parse_medicine(line) == out


def test_each_visit_has_its_own_prescription():
    visits = clinic_api.parse_timeline(MEDICINE_TIMELINE)
    assert [m["name"] for m in visits[0]["medicines"]] == ["Glimperide", "Telmisartan"]
    assert visits[0]["followups"] == [{"date": "2026-10-11", "status": "MISSED"}]  # not a medicine
    assert "medicines" not in visits[2]  # "none recorded"
    assert [m["name"] for m in visits[3]["medicines"]] == ["Glimipride", "low salt diet", "Metformin"]
    assert "labs" not in visits[0] and "labs" not in visits[3]


def test_current_medicines_are_the_latest_prescription_not_every_medicine_ever():
    summary = {**SUMMARY, "visits": [], "ongoing_medicines": ["Amlodipine", "Nucoxia", "Tramadol", "Glimperide"]}
    ctx = clinic_api.build_context(summary, MEDICINE_TIMELINE, {}, TODAY)
    assert ctx["medicines"]["from"] == "2026-10-01"
    assert ctx["medicines"]["items"] == [
        {"name": "Glimperide", "dosage": "1-0-0", "frequency": "Before food", "duration": "10 days"},
        {"name": "Telmisartan", "dosage": "1-0-0", "frequency": "After food", "duration": "10 days"}]
    assert [m["name"] for m in ctx["visits"][1]["medicines"]] == ["Amlodipine", "Telmisartan"]  # visit history


def test_two_visits_on_the_latest_day_give_one_prescription():
    """Two departments on one day: both prescriptions are current, each medicine once."""
    entries = sorted(clinic_api.parse_timeline(MEDICINE_TIMELINE)[1:], key=lambda e: e["date"], reverse=True)
    day, items = clinic_api.latest_prescription(entries)
    assert day == "2026-09-28"
    assert items == [{"name": "Amlodipine", "dosage": "1-0-0", "frequency": "After food", "duration": "10 days"},
                     {"name": "Telmisartan", "dosage": "1-0-0"}]


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
    # One BP reading (150/94, flagged BP_SYS_HIGH): since fix 03 (2026-11-20) the average of the
    # readings decides, and one reading means "control not known", with its 140/90 limits.
    assert {"asthma_uncontrolled", "arthritis_knee", "bp_controlled"} <= set(out["codes"])
    bp = next(c for c in out["conditions"] if c["code"] == "bp_controlled")
    assert bp["name"] == "BP, control not known (one reading in 90 days: 150/94)"
    assert out["severity"] == "severe"  # breathlessness, an emergency visit


@pytest.mark.parametrize("diagnosis", ["DJD knee spine", "DJD knee and spine", "DJD spine knee",
                                       "DJD spine and knee", "djd knee, spine"])
def test_djd_with_knee_and_spine_finds_both(db, diagnosis):
    """0abd37c0 (AI_TESTING note 15): "DJD knee spine" found only the knee."""
    timeline = f"DATE: 2026-08-19\n  VISIT ID: v1\n  Provisional Diagnosis (database): {diagnosis}\n"
    ctx = clinic_api.build_context({**SUMMARY, "visits": [], "long_term_conditions": [], "health_history": {}},
                                   timeline, {}, TODAY)
    ref = load_reference(db)
    ref.aliases = [ConditionAlias(**a) for a in _aliases(_from_csv()[0])]
    ref.warnings = []
    codes = {f.code for f in rule_findings(ctx, ref, TODAY).findings}
    assert {"arthritis_knee", "spondylosis"} <= codes


# ── The colleague's check: a warning, never a block (Option A, 2026-11-03) ──

def test_not_suitable_is_a_warning_line_for_the_doctor(ctx):
    note = eligibility_note(ctx)
    assert "not suitable for exercise" in note and "Cardiovascular" in note
    assert patient_profile(ctx)["eligibility_note"] == note
    assert eligibility_note({**ctx, "clinical_summary": {**ctx["clinical_summary"], "exercise_suitable": True}}) is None
    assert eligibility_note({k: v for k, v in ctx.items() if k != "clinical_summary"}) is None  # the database source


def test_not_suitable_shows_the_screenings_reason(ctx):
    # 1123000d (2026-11-05): "not suitable" only meant "no specific benefit".
    why = "No cluster where exercise gives a specific benefit (not harmful either)"
    note = eligibility_note({**ctx, "clinical_summary": {**ctx["clinical_summary"], "exercise_reason": why}})
    assert "not a safety check" in note and f"Its reason: {why}." in note
    assert "Its reason" not in eligibility_note(ctx)  # no reason given: no empty line


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


def test_visits_are_newest_first_even_when_the_timeline_lists_the_oldest_first():
    """The 2026-11-04 case: the timeline listed 2026-09-15 before 2026-09-21,
    so the older visit's note showed as the doctor's latest instructions."""
    timeline = """DATE: 2026-09-15
  VISIT ID: v1
  Chief Complaint (database): breathing problem while walking
  Prescription Instructions (database): Old case of HT, DM
  Medicines — Prescription (database):
    • Amlodipine, dosage 1-0-0
DATE: 2026-09-21
  VISIT ID: v2
  Chief Complaint (database): Follow up
  Prescription Instructions (database): Investigation --normal, BP --118/75
  Medicines — Prescription (database):
    • Telmisartan, dosage 1-0-0
"""
    summary = {"patient_id": "p8", "age_years": 65, "sex": "FEMALE",
               "visits": [{"visit_id": "v1", "visit_date": "2026-09-15", "doctor_id": "d1"},
                          {"visit_id": "v2", "visit_date": "2026-09-21", "doctor_id": "d1"}],
               "vitals": [{"visit_id": "v1", "visit_date": "2026-09-15", "readings": [{"label": "BP", "value": "123/80"}]},
                          {"visit_id": "v2", "visit_date": "2026-09-21", "readings": [{"label": "BP", "value": "118/75"}]}]}
    ctx = clinic_api.build_context(summary, timeline, {}, TODAY)
    assert [v["date"] for v in ctx["visits"]] == ["2026-09-21", "2026-09-15"]
    assert ctx["medicines"]["from"] == "2026-09-21"
    assert ctx["medicines"]["items"] == [{"name": "Telmisartan", "dosage": "1-0-0"}]
    assert ctx["medicines"]["patient_instructions"] == "Investigation --normal, BP --118/75"
    assert ctx["care"]["recent_complaints"][0]["date"] == "2026-09-21"


def test_visit_history_has_every_visit_and_costs_no_extra_call(monkeypatch):
    """The doctor's picker: all visits (the AI's record keeps the latest 10),
    from the /summary and /timeline already fetched when the patient opened."""
    timeline = "".join(f"DATE: 2026-{m:02d}-01\n  VISIT ID: v{m}\n  Prescription Instructions (database): note {m}\n"
                       for m in range(1, 13))  # 12 visits, oldest first
    summary = {"patient_id": "p7", "age_years": 50, "sex": "MALE", "visits": [], "vitals": []}
    responses = {"/patients/p7/summary": summary, "/patients/p7/timeline": {"timeline": timeline},
                 "/patients/kid/summary": {**summary, "age_years": 9}, "/doctors": {"doctors": []}}
    calls = []
    monkeypatch.setattr(patient_api, "get", lambda path, **_: calls.append(path) or responses.get(path))
    clinic_api._cache.clear()
    ctx = clinic_api.patient_context("p7")
    history = clinic_api.visit_history("p7")
    assert len(ctx["visits"]) == 10 and len(history) == 12
    assert [v["patient_instructions"] for v in history[:2]] == ["note 12", "note 11"]
    assert history[-1]["date"] == "2026-01-01"
    assert calls.count("/patients/p7/summary") == 1 and calls.count("/patients/p7/timeline") == 1
    assert clinic_api.visit_history("kid") is None and clinic_api.visit_history("nobody") is None
    clinic_api._cache.clear()


# ── The colleague's flags reach the AI's concerns, not its evidence (2026-11-16) ──

# bd8b445c's flags (2026-11-16), shortened.
FLAGS = [
    {"level": "high", "title": "Type 2 diabetes mellitus: HbA1c / glucose out of range", "evidence": "HbA1c 7.6 %",
     "kind": "condition", "time": "current", "as_of": "", "undated": True},
    {"level": "high", "title": "1 missed follow-up incl. the latest", "evidence": "due 2026-10-11",
     "kind": "followup", "time": "current", "as_of": "2026-10-01"},
    {"level": "high", "title": "Visual symptoms with diabetes", "evidence": "blurred vision (#1, #2)",
     "kind": "risk", "time": "past", "as_of": "2026-05-29"},
    {"level": "high", "title": "Repeated oral NSAIDs with Hypertension", "evidence": "Nucoxia",
     "kind": "medication", "time": "past", "as_of": "2026-09-17"},
    {"level": "medium", "title": "Pulse above 100", "evidence": "110 bpm (#3)",  # an old past flag (made up for the test)
     "kind": "risk", "time": "past", "as_of": "2026-04-01"},
]


def test_clinic_flags_sent_to_the_ai():
    from agent.assess import clinic_flags
    lines = clinic_flags({"clinical_summary": {"flags": FLAGS}}, date(2026, 11, 16), 183)
    assert lines == [
        "high: Type 2 diabetes mellitus: HbA1c / glucose out of range (HbA1c 7.6 %) [undated]",
        "high: 1 missed follow-up incl. the latest (due 2026-10-11) [current, last seen 2026-10-01]",
        "high: Visual symptoms with diabetes (blurred vision (#1, #2)) [past, last seen 2026-05-29]",  # 171 days
    ]  # left out: the medicine flag, and the past flag older than 183 days
    assert clinic_flags({"clinical_summary": None}, TODAY, 183) == [] == clinic_flags({}, TODAY, 183)  # DB source


def test_the_flag_window_comes_from_time_windows_csv(db):
    assert load_reference(db).flag_days() == 183


def test_a_quote_found_only_in_the_flags_is_not_evidence(db, ctx):
    """The flags go to the AI apart from PATIENT_RECORD, so a condition the
    AI 'finds' in a flag's wording is dropped like any other unfound quote."""
    from agent.assess import AIAssessment, AIFinding, _check, _record
    ctx = {**ctx, "clinical_summary": {"flags": [{"level": "high", "title": "Visual symptoms with diabetes",
                                                  "evidence": "blurred vision (#1)"}]}}
    ai = AIAssessment(conditions=[AIFinding(code="neurological", quote="Visual symptoms with diabetes",
                                            where="clinic flags")],
                      problem="", body_area="general", severity="moderate")
    kept, dropped, _ = _check(ai, load_reference(db), _record(ctx), TODAY)
    assert kept == [] and dropped[0]["why"] == "quote not found in the record"


# ── Medicines the assessment AI sees: recent visits only (2026-11-16) ──────

def test_the_ai_sees_medicines_only_from_recent_visits(db):
    """MEDICINE_TIMELINE: visits on 2026-10-01, 2026-09-28 (two) and 2026-08-27.
    On 2026-12-01 with a 90-day window, 2026-08-27 (96 days) loses its medicines."""
    from agent.assess import _record
    ref = load_reference(db)
    assert ref.medicine_days() == 90  # data/time_windows.csv, row "medicine"
    ctx = clinic_api.build_context({**SUMMARY, "visits": []}, MEDICINE_TIMELINE, {}, TODAY)
    visits = _record(ctx, date(2026, 12, 1), ref.medicine_days())["visits"]
    assert [(v["date"], len(v.get("medicines", []))) for v in visits] == [  # one visit per date (fix 10)
        ("2026-10-01", 2), ("2026-09-28", 2), ("2026-08-27", 0)]
    assert visits[2]["date"] == "2026-08-27"  # the visit itself stays, only its medicines go
    assert ctx["visits"][2]["medicines"]  # the doctor's screen still has them
    assert len(_record(ctx)["visits"][2]["medicines"]) == 3  # no window given: unchanged


def test_an_old_medicine_is_not_evidence(db):
    """A medicine left out by the window can't be quoted for a condition."""
    from agent.assess import AIAssessment, AIFinding, _check, _record
    ref = load_reference(db)
    ctx = clinic_api.build_context({**SUMMARY, "visits": []}, MEDICINE_TIMELINE, {}, TODAY)
    ai = AIAssessment(conditions=[AIFinding(code="diabetes_any", quote="Metformin", where="visit 2026-08-27, medicines")],
                      problem="", body_area="general", severity="moderate")
    kept, dropped, _ = _check(ai, ref, _record(ctx, date(2026, 12, 1), 90), date(2026, 12, 1))
    assert kept == [] and dropped[0]["why"] == "quote not found in the record"


# ── Flag and medicine notes (2026-11-16) ───────────────────────────────────

def test_medicine_notes_join_the_concerns_one_per_medicine():
    """bd8b445c (2026-11-16): the AI put three medicines in one note."""
    from agent.assess import AIAssessment, shown_text
    ai = AIAssessment(conditions=[], problem="Diabetes with controlled BP", body_area="back", severity="moderate",
                      concerns=["Back pain is long-standing"],
                      medicine_notes=["Glimperide: risk of low sugar during or after exercise, carry something sweet; "
                                      "Telmisartan: dizziness when standing up, rise slowly and drink water.",
                                      "Medicine: Tab B-blocker 25 mg: the pulse rises less"])
    assert shown_text(ai) == {"problem": "Diabetes with BP", "concerns": [
        "Back pain is long-standing",
        "Medicine: Glimperide: risk of low sugar during or after exercise, carry something sweet",
        "Medicine: Telmisartan: dizziness when standing up, rise slowly and drink water",
        "Medicine: Tab B-blocker 25 mg: the pulse rises less"]}  # not "Medicine: Medicine: ..."


def test_clinic_flag_concerns_are_written_in_code_with_their_dates():
    """The AI dropped "last seen" dates (2026-11-16): the lines come from the flags themselves."""
    from agent.assess import flag_concerns
    flags = [*FLAGS, {"level": "medium", "title": "BP at/above 130/80 target at latest visit", "kind": "risk",
                      "time": "current", "as_of": "2026-10-01",
                      "evidence": "Last 3 readings: 134/82, 135/76 · similar to the 9 earlier readings · on Telmisartan"}]
    assert flag_concerns({"clinical_summary": {"flags": flags}}, date(2026, 11, 16), 183) == [
        "Clinic flag: Type 2 diabetes mellitus: HbA1c / glucose out of range: HbA1c 7.6 % (undated)",
        "Clinic flag: 1 missed follow-up incl. the latest: due 2026-10-11 (current, last seen 2026-10-01)",
        "Clinic flag: Visual symptoms with diabetes: blurred vision (#1, #2) (past, last seen 2026-05-29)",
        "Clinic flag: BP at/above 130/80 target at latest visit: Last 3 readings: 134/82, 135/76 "
        "(current, last seen 2026-10-01)"]  # no medicine flag, no old past flag, no medicine in the evidence
    assert flag_concerns({}, TODAY, 183) == []  # the DB source: none


@pytest.mark.parametrize("where, quote, other_where, other_quote, same", [
    ("BMI measured 2026-10-01", "BMI 30.8", "measured on 2026-10-01", "BMI 30.8", True),
    ("visit 2026-09-28, complaint", "Follow up -k/C/o-HTN-DM, general weakness",
     "visit 2026-09-28, complaint", "K/C/o-HTN-DM, general weakness", True),  # the AI quoted part of it
    ("visit 2026-09-17, complaint", "Follow up -K/C/o-HTN,DM, report check",
     "visit 2026-09-17, complaint", "Follow up -K/C/o-HTN-DM, report check", True),  # only punctuation differs
    ("doctor recorded", "Hypertension", "doctor recorded", "Hypertension", True),
    ("visit 2026-09-17, diagnosis", "Cervical pain", "visit 2026-07-10, diagnosis", "Cervical pain", False),  # other visit
    ("doctor recorded", "Hypertension", "health history", "hypertension", False),  # other source
    # 6959e408 (2026-11-18): the AI adds the item after a comma; still the same source
    ("health history", "hypertension", "health history, hypertension", "hypertension", True),
    ("doctor recorded", "Hypertension", "health history, hypertension", "hypertension", False),
    # bd8b445c (2026-11-16): a diagnosis inside the same day's complaint is not the same evidence
    ("visit 2026-06-18, complaint", "Domestic fall yesterday,lt hand stuck and shoulder pain",
     "visit 2026-06-18, diagnosis", "Shoulder pain", False),
    ("visit 2026-07-10, complaint", "Follow up HTN, Dm, acidity", "visit 2026-07-10, diagnosis", "Htn", False)])
def test_the_same_evidence_is_shown_once(where, quote, other_where, other_quote, same):
    from agent.routing import _same_evidence
    assert _same_evidence(where, quote, other_where, other_quote) is same


def test_every_rules_evidence_line_is_kept_and_only_the_ais_repeat_goes(db):
    """Through finalize: the rules' complaint and diagnosis lines of one day
    both stay; the AI's partial copy of the complaint goes."""
    from agent.conditions import Finding, RuleResult
    from agent.routing import finalize
    rules = RuleResult(findings=[
        Finding("spondylosis", "rules", "visit 2026-07-10, diagnosis", "Cervical pain"),
        Finding("spondylosis", "rules", "visit 2026-07-10, complaint", "Follow up, back pain, neck pain, cervical pain"),
    ], unmapped=[], warnings=[])
    ai = [Finding("spondylosis", "ai", "visit 2026-07-10, chief_complaint", "back pain, neck pain"),
          Finding("spondylosis", "ai", "visit 2026-09-17, diagnosis_confirmed", "Cervical pain")]
    ctx = {"visits": [], "vital_flags": [], "conditions": {"doctor_recorded": []}, "alerts": {"emergencies": []},
           "patient": {"age": 50}, "body": {}}
    result = finalize(ctx, load_reference(db), rules, None, ai)
    [g] = [c for c in result["conditions"] if c["code"] == "spondylosis"]
    assert g["evidence"] == ['visit 2026-07-10, diagnosis: "Cervical pain"',
                             'visit 2026-07-10, complaint: "Follow up, back pain, neck pain, cervical pain"',
                             'visit 2026-09-17, diagnosis: "Cervical pain"']  # another visit: kept


def test_raw_field_names_in_the_ais_evidence_are_reworded():
    from agent.routing import _tidy_where
    assert _tidy_where("visit 2026-10-01, diagnosis_provisional") == "visit 2026-10-01, diagnosis"
    assert _tidy_where("visit 2026-09-17, diagnosis_confirmed") == "visit 2026-09-17, diagnosis"
    assert _tidy_where("recorded_conditions") == "doctor recorded"


def test_the_ai_gets_the_latest_prescription_only_while_it_is_taken():
    """Fix 04 (2026-11-20): a course ends at prescription date + duration."""
    from agent.assess import ENDED, _record
    ctx = clinic_api.build_context({**SUMMARY, "visits": []}, MEDICINE_TIMELINE, {}, TODAY)
    assert _record(ctx, date(2026, 10, 5), 90)["latest_prescription"] == {
        "date": "2026-10-01", "medicines": ctx["medicines"]["items"]}  # 10-day courses from 1 Oct: still taken
    assert _record(ctx, date(2026, 11, 16), 90)["latest_prescription"] == {  # ended on 11 Oct: said so
        "date": "2026-10-01", "medicines": [], "note": ENDED}
    assert _record({**ctx, "medicines": {"from": None, "items": []}}, TODAY, 90)["latest_prescription"] is None


@pytest.mark.parametrize("item, days", [
    ({"name": "Amlodipine", "duration": "10 days"}, 10),
    ({"name": "Azee — 1-0-0 · After food · 5 days"}, 5),                     # the API's one-line form
    ({"name": "vitamin D3 60000 — 0-1-0 · After food · 15 days"}, 15),       # a number in the name isn't the length
    ({"name": "Thyronorm", "duration": "2 weeks"}, 14),
    ({"name": "Metformin", "duration": "1 month"}, 30),
    ({"name": "Clotrimazole + miconazole — 1-1-1"}, None),                   # no duration written
])
def test_course_days(item, days):
    from agent.assess import course_days
    assert course_days(item) == days


def test_only_the_medicines_still_taken_reach_the_ai():
    """30ca6dbf: a 5- and a 7-day course from 26 Sep, draft on 20 Nov; plus a
    medicine with no duration, which keeps the 90-day window."""
    from agent.assess import ENDED, _latest_prescription
    ctx = {"medicines": {"from": "2026-09-26", "items": [
        {"name": "Cough syrup — 1-0-1 · After food · 5 days"}, {"name": "Cetirizine — 0-0-1 · After food · 7 days"},
        {"name": "Thyronorm — 1-0-0 · 90 days"}, {"name": "Inhaler — SOS"}]}}
    out = _latest_prescription(ctx, date(2026, 11, 20), 90)
    assert [m["name"].split(" —")[0] for m in out["medicines"]] == ["Thyronorm", "Inhaler"]
    assert _latest_prescription(ctx, date(2027, 1, 20), 90) == {  # everything over: said so, not "not known"
        "date": "2026-09-26", "medicines": [], "note": ENDED}


@pytest.mark.parametrize("name, key", [
    ("Glucose", "nonfasting_sugar_mg_dl"), ("BLOOD SUGAR RANDOM", "nonfasting_sugar_mg_dl"),  # 016e4c77
    ("Blood Sugar Fasting", "fasting_sugar_mg_dl"), ("Fasting Blood Glucose", "fasting_sugar_mg_dl")])
def test_sugar_lab_names_reach_the_reading_rules(name, key):
    assert clinic_api.lab_readings([{"name": name, "value": "312 mg/dL", "status": "High"}]) == {key: 312.0}
    assert clinic_api.lab_readings([{"name": name, "value": "17.3 mmol/L", "status": "High"}]) == {}  # other unit


# The doctor's typed record wins over a scanned document's OCR (2026-11-17,
# 0017c9d8): the scans were often the previous visit's prescription, or a form
# heading read as a diagnosis. A scan fills a field only when nothing was typed.
DOCUMENT_TIMELINE = """DATE: 2026-09-10
  VISIT ID: v3
  Chief Complaint (database): Eczema
  Provisional Diagnosis (database): LSC
  Confirmed Diagnosis (database): Not Documented
  Supporting Document(s): 3 found
    --- Document 2 ---
    Provisional Diagnosis (Document 2): Eczema
    Chief Complaint (Document 2): Eczema
    --- Document 3 ---
    Provisional Diagnosis (Document 3): BP pulse SPo2 Sign
DATE: 2026-07-14
  VISIT ID: v2
  Chief Complaint (database): Fungal infection on leg and buttocks, itching
  Provisional Diagnosis (database): Eczema
  Confirmed Diagnosis (database): Not Documented
    --- Document 1 ---
    Clinical Impression (Document 1): Eczema
    Chief Complaint (Document 1): Dark patches on leg and itching
    --- Document 2 ---
    Provisional Diagnosis (Document 2): HTn G6A2B1C0
DATE: 2026-07-04
  VISIT ID: v1
  Chief Complaint (database): Not Documented
  Provisional Diagnosis (database): Not Documented
    --- Document 1 ---
    Provisional Diagnosis (Document 1): Eczema
    Chief Complaint (Document 1): Dark patches on leg
"""


def test_typed_record_wins_over_scanned_documents():
    v3, v2, v1 = clinic_api.parse_timeline(DOCUMENT_TIMELINE)
    assert (v3["complaint"], v3["provisional"]) == ("Eczema", "LSC")
    assert (v2["complaint"], v2["provisional"]) == ("Fungal infection on leg and buttocks, itching", "Eczema")
    assert v2["confirmed"] is None and "from_document" not in v2


def test_a_scan_fills_a_field_nothing_was_typed_in():
    v1 = clinic_api.parse_timeline(DOCUMENT_TIMELINE)[2]
    assert (v1["complaint"], v1["provisional"]) == ("Dark patches on leg", "Eczema")
    assert v1["from_document"] == ["provisional", "complaint"]


# ── One visit per date, and the older complaints (fix 10, 2026-11-20) ───────
# 6959e408: 20 records, two a day; the latest 10 were only 6 dates, so
# "Muscles pain in legs" (14 Jul, the 11th record) reached nobody.

def test_records_of_one_day_become_one_visit():
    a = {"date": "2026-09-17", "complaint": "Itching,follow up", "doctor": "Dr A", "vitals": {"bp": "130/90", "pulse": 96.0},
         "medicines": [{"name": "Cetirizine"}]}
    b = {"date": "2026-09-17", "complaint": "Itching,follow up", "diagnosis_provisional": "Tinea", "doctor": "Dr B",
         "vitals": {"pulse": 93.0, "spo2": 99.0}, "medicines": [{"name": "Cetirizine"}, {"name": "Itraconazole"}]}
    c = {"date": "2026-08-29", "complaint": "Follow up"}
    [day, other] = clinic_api.merge_same_day([a, b, c])
    assert day["complaint"] == "Itching,follow up" and day["diagnosis_provisional"] == "Tinea"
    assert day["doctor"] == "Dr A / Dr B"
    assert day["vitals"] == {"bp": "130/90", "pulse": 96.0, "spo2": 99.0}  # the first record's reading wins
    assert [m["name"] for m in day["medicines"]] == ["Cetirizine", "Itraconazole"]
    assert other == c


def test_two_complaints_on_one_day_are_both_kept():
    [day] = clinic_api.merge_same_day([{"date": "2026-07-20", "complaint": "Htn , weakness"},
                                       {"date": "2026-07-20", "complaint": "Itching, tinea"}])
    assert day["complaint"] == "Htn , weakness; Itching, tinea"


def test_older_complaints_reach_the_ai_within_the_window():
    from agent.assess import older_complaints
    ctx = {"visits": [{"date": "2026-10-10"}, {"date": "2026-07-20"}],
           "visits_all": [{"date": "2026-10-10", "complaint": "Follow up"}, {"date": "2026-07-20", "complaint": "Htn"},
                          {"date": "2026-07-14", "complaint": "Muscles pain in legs"},
                          {"date": "2026-07-14", "complaint": "Follow up"},
                          {"date": "2026-01-10", "complaint": "Knee pain"}]}  # older than 183 days
    assert older_complaints(ctx, date(2026, 11, 20), 183) == [
        {"date": "2026-07-14", "complaint": "Muscles pain in legs"}, {"date": "2026-07-14", "complaint": "Follow up"}]


def test_leg_pain_is_a_concern_not_a_stop(db):
    from agent.conditions import load_reference, rule_findings
    from agent.routing import finalize
    from store.models import WarningComplaint
    from store.seed import _rows
    ref = load_reference(db)
    ref.warnings = [WarningComplaint(phrase=r["phrase"].strip().lower(), label=r["label"],
                                     stops=r["stops"].strip().lower() != "no") for r in _rows("warning_complaints.csv")]
    ctx = {"visits": [{"date": "2026-07-14", "complaint": "Muscles pain in legs", "vitals": {}}], "vital_flags": [],
           "alerts": {"emergencies": []}, "patient": {"age": 57}, "body": {},
           "conditions": {"doctor_recorded": [], "long_term_conditions": [], "health_history": []}}
    out = finalize(ctx, ref, rule_findings(ctx, ref, date(2026, 11, 20)), None, [], date(2026, 11, 20))
    assert not any("pain" in r.lower() for r in out["severe_reasons"])
    assert any(c.startswith('Leg or muscle pain (ask: pain on walking?) in the complaint on 2026-07-14: '
                            '"Muscles pain in legs". Not a stop on its own') for c in out["concerns"])



def test_the_ais_not_listed_item_is_dropped_when_a_rules_concern_shows_it():
    """6959e408 (test run 2026-11-20): the leg pain showed twice."""
    from agent.assess import new_unlisted
    rules = ['Leg or muscle pain (ask: pain on walking?) in the complaint on 2026-07-14: "Muscles pain in legs". '
             "Not a stop on its own: please ask about it before approving."]
    unlisted = ['Not in our exercise list: "Muscles pain in legs" (visit 2026-07-14, complaint)',
                'Not in our exercise list: "Shoulder pain" (visit 2026-07-14, complaint)']
    assert new_unlisted(unlisted, rules) == [unlisted[1]]
