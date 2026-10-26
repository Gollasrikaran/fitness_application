"""Everything the testbed reads from the live clinic database.

Only clinical facts are selected. Names, phone numbers, addresses,
government IDs and uploaded documents are never read for patients (see
FEATURES.txt). Doctors are staff, so their names are shown.
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from app.db import fetch_all, fetch_one

# A patient record the agent may use: not deleted, not a test record, and
# not merged into another record.
_LIVE_PATIENT = "p.deleted_at IS NULL AND NOT p.is_demo AND p.merged_into_patient_id IS NULL"

# Health-history questionnaire items that are conditions (the rest are
# habits or free-text notes, kept separately).
_HISTORY_CONDITIONS = ("hypertension", "diabetes", "thyroid", "heart_disease", "asthma",
                       "high_cholesterol", "tuberculosis")
_HISTORY_OTHER = ("surgeries", "hospitalisations", "drug_allergies", "smoking", "alcohol")

_VITAL_KEYS = ("bp", "bp_sys", "bp_dia", "pulse", "spo2", "temp_f", "temp_c", "sugar_mg_dl",
               "fasting_sugar_mg_dl", "nonfasting_sugar_mg_dl", "hb", "weight_kg", "height_cm", "bmi")
RECENT_VISITS = 10       # visits the context looks back over
FLAG_VISITS = 5          # visits whose vital flags count as "recent"
MIN_AGE = 18             # the agent is for adults

# The patient's latest completed visits, as a subquery every context query
# can use, so they all run independently (and in parallel).
_RECENT_VISIT_IDS = """SELECT id FROM visit WHERE patient_id = %(id)s::uuid AND deleted_at IS NULL
                       AND status = 'COMPLETED' ORDER BY created_at DESC LIMIT {n}"""


def doctors() -> list[dict]:
    """Doctors who have seen at least one patient, busiest first."""
    return fetch_all("""
        SELECT u.id::text AS id, trim(concat_ws(' ', u.first_name, u.last_name)) AS name,
               u.specialization, count(DISTINCT v.patient_id) AS patients
        FROM "user" u
        JOIN visit v ON v.assigned_doctor_user_id = u.id AND v.deleted_at IS NULL
        WHERE u.role = 'DOCTOR'
        GROUP BY u.id
        ORDER BY patients DESC
    """)


def patients(doctor_id: str | None, search: str, limit: int, min_visits: int,
             min_age: int = MIN_AGE) -> list[dict]:
    """Patients with completed visits, most recently seen first. With a
    doctor, only that doctor's patients."""
    return fetch_all(f"""
        WITH seen AS (
            SELECT v.patient_id, count(*) AS visits, max(v.created_at) AS last_visit
            FROM visit v
            WHERE v.deleted_at IS NULL AND v.status = 'COMPLETED'
              AND (%(doctor)s::uuid IS NULL OR v.assigned_doctor_user_id = %(doctor)s::uuid)
            GROUP BY v.patient_id
            HAVING count(*) >= %(min_visits)s
        )
        SELECT p.id::text AS id, p.age_years AS age, p.sex, s.visits, s.last_visit::date AS last_visit,
               (SELECT coalesce(jsonb_agg(e.key ORDER BY e.key), '[]'::jsonb)
                FROM jsonb_each(CASE WHEN jsonb_typeof(p.health_history_json) = 'object'
                                     THEN p.health_history_json ELSE '{{}}'::jsonb END) e
                WHERE e.key = ANY(%(conditions)s) AND (e.value ->> 'present') = 'true') AS history
        FROM seen s JOIN patient p ON p.id = s.patient_id
        WHERE {_LIVE_PATIENT}
          AND p.age_years >= %(min_age)s
          AND (%(search)s = '' OR p.id::text LIKE %(search)s || '%%')
        ORDER BY s.last_visit DESC
        LIMIT %(limit)s
    """, {"doctor": doctor_id, "search": search.strip().lower(), "limit": limit,
          "min_visits": min_visits, "min_age": min_age, "conditions": list(_HISTORY_CONDITIONS)})


def doctor_name(doctor_id: str) -> str | None:
    """A doctor's name (staff, so shown), or None for an unknown id."""
    try:
        row = fetch_one("""SELECT trim(concat_ws(' ', first_name, last_name)) AS name FROM "user"
                           WHERE id = %(id)s::uuid AND role = 'DOCTOR'""", {"id": doctor_id})
    except Exception:  # not a clinic id (e.g. a test doctor)
        return None
    return (row or {}).get("name") or None


def patient_briefs(ids: list[str]) -> dict[str, dict]:
    """Age and sex for a list of patients (e.g. the review queue), by id."""
    if not ids:
        return {}
    rows = fetch_all("SELECT p.id::text AS id, p.age_years AS age, p.sex FROM patient p "
                     "WHERE p.id = ANY(%(ids)s::uuid[])", {"ids": list(ids)})
    return {r["id"]: r for r in rows}


def _number(value):
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _vitals(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {k: raw[k] for k in _VITAL_KEYS if raw.get(k) not in (None, "")}


def _medicine(item: dict) -> dict:
    return {k: item[k] for k in ("name", "dosage", "frequency", "duration", "notes") if item[k] not in (None, "")}


def _visit_entry(visit: dict, rx: dict | None, medicines_by_rx: dict) -> dict:
    """One visit with what the doctor recorded at it, empty fields left out."""
    entry = {"date": visit["date"], "doctor": visit["doctor"] or None, "complaint": visit["chief_complaint"],
             "duration": visit["complaint_duration"], "vitals": _vitals(visit["vitals_json"])}
    if rx:
        entry |= {"diagnosis_provisional": rx["provisional"], "diagnosis_confirmed": rx["confirmed"],
                  "medicines": medicines_by_rx.get(rx["id"], []), "patient_instructions": rx["patient_instructions"],
                  "follow_up_at": rx["follow_up_at"], "emergency": rx["is_emergency"] or None}
        if rx["is_referral_recommended"]:
            entry["referral"] = {"to": rx["referral_specialist_name"], "for": rx["referral_treatment_name"]}
    return {k: v for k, v in entry.items() if v not in (None, "", [], {})}


def _context_queries() -> dict[str, tuple[str, str]]:
    """name -> (fetch kind, SQL). All take only %(id)s, so they run in parallel."""
    recent = _RECENT_VISIT_IDS.format(n=RECENT_VISITS)
    return {
        "patient": ("one", f"""
            SELECT p.id::text AS id, p.age_years, p.sex, p.preferred_language, p.created_at::date AS registered_on,
                   p.health_history_json, p.long_term_conditions
            FROM patient p WHERE p.id = %(id)s::uuid AND {_LIVE_PATIENT}"""),
        "totals": ("one", """
            SELECT count(*) AS visits, min(created_at)::date AS first_visit, max(created_at)::date AS last_visit
            FROM visit WHERE patient_id = %(id)s::uuid AND deleted_at IS NULL AND status = 'COMPLETED'"""),
        "visits": ("all", f"""
            SELECT v.id::text AS id, v.created_at::date AS date, v.chief_complaint, v.complaint_duration, v.vitals_json,
                   trim(concat_ws(' ', u.first_name, u.last_name)) AS doctor
            FROM visit v LEFT JOIN "user" u ON u.id = v.assigned_doctor_user_id
            WHERE v.id IN ({recent}) ORDER BY v.created_at DESC"""),
        "prescriptions": ("all", f"""
            SELECT pr.id::text AS id, pr.visit_id::text AS visit_id, pr.created_at::date AS date,
                   nullif(trim(pr.provisional_diagnosis), '') AS provisional,
                   nullif(trim(pr.confirmed_diagnosis), '') AS confirmed,
                   pr.is_emergency, pr.is_referral_recommended, pr.referral_specialist_name,
                   pr.referral_treatment_name, nullif(trim(pr.patient_instructions), '') AS patient_instructions,
                   pr.follow_up_at::date AS follow_up_at
            FROM prescription pr
            WHERE pr.visit_id IN ({recent}) AND pr.deleted_at IS NULL
            ORDER BY pr.created_at DESC"""),
        "medicines": ("all", f"""
            SELECT pi.prescription_id::text AS prescription_id, pi.medication_name AS name,
                   pi.dosage, pi.frequency, pi.duration, pi.notes
            FROM prescriptionitem pi JOIN prescription pr ON pr.id = pi.prescription_id
            WHERE pr.visit_id IN ({recent}) AND pr.deleted_at IS NULL
            ORDER BY pi.created_at"""),
        "flags": ("all", f"""
            SELECT f.recorded_at::date AS date, f.metric, f.code, f.severity, f.value
            FROM visit_vital_flag f
            WHERE f.visit_id IN ({_RECENT_VISIT_IDS.format(n=FLAG_VISITS)}) AND f.tier <> 'IMPLAUSIBLE'
            ORDER BY f.recorded_at DESC, f.severity"""),
        "recorded": ("all", """
            SELECT l.name, pc.severity, pc.status, pc.diagnosed_at
            FROM patient_condition pc JOIN long_term_condition l ON l.id = pc.long_term_condition_id
            WHERE pc.patient_id = %(id)s::uuid AND pc.deleted_at IS NULL
            ORDER BY l.name"""),
        "followups": ("one", """
            SELECT count(*) FILTER (WHERE status = 'PENDING') AS pending,
                   min(scheduled_date) FILTER (WHERE status = 'PENDING') AS next_due,
                   count(*) FILTER (WHERE status = 'MISSED') AS missed,
                   max(scheduled_date) FILTER (WHERE status = 'MISSED') AS last_missed,
                   count(*) FILTER (WHERE is_emergency) AS emergency
            FROM followup_schedule WHERE patient_id = %(id)s::uuid"""),
        "episodes": ("all", """
            SELECT parent_visit_date::date AS since, chief_complaint, confirmed_diagnoses_json AS diagnoses, status
            FROM patient_disease_journey
            WHERE patient_id = %(id)s::uuid AND status IN ('OPEN', 'ACTIVE_FOLLOWUP')
            ORDER BY parent_visit_date DESC"""),
        "tasks": ("all", """
            SELECT task_type, priority, status, due_date
            FROM care_task
            WHERE patient_id = %(id)s::uuid AND deleted_at IS NULL AND status IN ('OPEN', 'CLAIMED')
            ORDER BY due_date"""),
    }


def patient_context(patient_id: str) -> dict | None:
    """What the agent knows about one patient, grouped as in FEATURES.txt."""
    queries = _context_queries()
    args = {"id": patient_id}
    with ThreadPoolExecutor(max_workers=len(queries)) as run:
        futures = {name: run.submit(fetch_one if kind == "one" else fetch_all, sql, args)
                   for name, (kind, sql) in queries.items()}
        r = {name: f.result() for name, f in futures.items()}
    p = r["patient"]
    if p is None:
        return None
    visits, prescriptions = r["visits"], r["prescriptions"]
    latest_rx = prescriptions[0] if prescriptions else None
    totals, followups = r["totals"], r["followups"]
    flags, recorded, episodes, tasks = r["flags"], r["recorded"], r["episodes"], r["tasks"]
    medicines_by_rx = defaultdict(list)
    for item in r["medicines"]:
        medicines_by_rx[item["prescription_id"]].append(_medicine(item))
    rx_by_visit = {}
    for rx in prescriptions:  # newest first, so a visit keeps its latest prescription
        rx_by_visit.setdefault(rx["visit_id"], rx)

    history = p["health_history_json"] if isinstance(p["health_history_json"], dict) else {}
    def answered(keys):
        out = []
        for key in keys:
            item = history.get(key)
            if isinstance(item, dict) and item.get("present"):
                out.append({"item": key, "notes": (item.get("notes") or "").strip() or None})
        return out

    # Latest visit that has a weight; height from the latest visit that has one.
    weight = next(((v["date"], _number(v["vitals_json"].get("weight_kg"))) for v in visits
                   if isinstance(v["vitals_json"], dict) and _number(v["vitals_json"].get("weight_kg"))), (None, None))
    height = next((_number(v["vitals_json"].get("height_cm")) for v in visits
                   if isinstance(v["vitals_json"], dict) and _number(v["vitals_json"].get("height_cm"))), None)
    bmi = round(weight[1] / (height / 100) ** 2, 1) if weight[1] and height and 100 <= height <= 230 else None

    return {
        "patient": {"id": p["id"], "age": p["age_years"], "sex": p["sex"],
                    "language": p["preferred_language"], "registered_on": p["registered_on"]},
        "body": {"weight_kg": weight[1], "height_cm": height, "bmi": bmi, "measured_on": weight[0]},
        "conditions": {
            "doctor_recorded": recorded,
            "health_history": answered(_HISTORY_CONDITIONS),
            "long_term_conditions": p["long_term_conditions"] or [],
            "recent_diagnoses": [{"date": r["date"], "provisional": r["provisional"], "confirmed": r["confirmed"]}
                                 for r in prescriptions if r["provisional"] or r["confirmed"]],
        },
        "history_other": answered(_HISTORY_OTHER),
        "vitals_recent": [{"date": v["date"], **_vitals(v["vitals_json"])} for v in visits],
        "vital_flags": flags,
        "visits": [_visit_entry(v, rx_by_visit.get(v["id"]), medicines_by_rx) for v in visits],
        "medicines": {"from": latest_rx["date"] if latest_rx else None,
                      "items": medicines_by_rx[latest_rx["id"]] if latest_rx else [],
                      "patient_instructions": latest_rx["patient_instructions"] if latest_rx else None,
                      "follow_up_at": latest_rx["follow_up_at"] if latest_rx else None},
        "care": {
            **(totals or {}),
            "recent_complaints": [{"date": v["date"], "complaint": v["chief_complaint"],
                                   "duration": v["complaint_duration"], "doctor": v["doctor"]}
                                  for v in visits if v["chief_complaint"]],
            "followups": followups,
            "open_episodes": episodes,
            "open_tasks": tasks,
        },
        "alerts": {
            "emergencies": [{"date": r["date"], "diagnosis": r["confirmed"] or r["provisional"]}
                            for r in prescriptions if r["is_emergency"]],
            "referrals": [{"date": r["date"], "to": r["referral_specialist_name"],
                           "for": r["referral_treatment_name"]} for r in prescriptions if r["is_referral_recommended"]],
        },
        "as_of": date.today(),
    }
