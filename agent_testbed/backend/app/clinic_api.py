"""Everything the testbed reads, from the colleague's Patient Intelligence API
instead of the clinic database (CLINIC_SOURCE=api, see app/source.py).

Same five functions and the same shapes as app/clinic.py, so the agent,
rules and screens don't change. Two calls per patient record: /summary
(conditions, vitals, flags, her analysis) and /timeline (complaints and
diagnoses and lab results per visit, as text). What the API doesn't have
(complaint duration, follow-ups, open episodes and care tasks) is left empty.

Extra, API only: context["labs"], lab results from the visits' documents
(Hb and sugar also go into the visit's vitals, for the reading rules), and
context["clinical_summary"] (can exercise or not, main type, clinical flags).
The doctor sees the summary as information and a warning; it never decides
the plan (decided 2026-11-03).
"""
from __future__ import annotations

import re
import threading
import time
from datetime import date

from app import patient_api
from app.clinic import _HISTORY_CONDITIONS, _HISTORY_OTHER, FLAG_VISITS, MIN_AGE, RECENT_VISITS

_CACHE_SECONDS = 300  # API answers are reused for 5 minutes
_cache: dict[tuple, tuple[float, object]] = {}
_lock = threading.Lock()

# Age and sex per patient, remembered for a day (they barely change): from the
# record of a patient the doctor opened, or from /demographics (one patient a
# call, used only for the review queue). Lists use only what is remembered.
_PEOPLE_SECONDS = 24 * 3600
_people: dict[str, tuple[float, dict]] = {}


def _cached(path: str, **params):
    key = (path, tuple(sorted(params.items())))
    with _lock:
        hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    value = patient_api.get(path, **params)
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def _cached_summary(patient_id: str) -> dict | None:
    """The summary if this patient was opened recently, without calling the API."""
    with _lock:
        hit = _cache.get((f"/patients/{patient_id}/summary", ()))
    return hit[1] if hit and time.monotonic() - hit[0] < _CACHE_SECONDS else None


def _remember(patient_id: str, age, sex) -> dict:
    person = {"id": patient_id, "age": age, "sex": _sex(sex)}
    with _lock:
        _people[patient_id] = (time.monotonic(), person)
    return person


def _known(patient_id: str) -> dict | None:
    """Age and sex if known, without calling the API."""
    with _lock:
        hit = _people.get(patient_id)
    return hit[1] if hit and time.monotonic() - hit[0] < _PEOPLE_SECONDS else None


def _demographics(patient_id: str) -> dict | None:
    """Age and sex: remembered, or one /demographics call (four fields, no AI)."""
    person = _known(patient_id)
    if person is None:
        d = patient_api.get(f"/patients/{patient_id}/demographics")
        person = _remember(patient_id, d.get("age_years"), d.get("sex")) if d else None
    return person


# ── Parsing the API's text values ───────────────────────────────────────────

# Vitals labels in /summary -> our vitals_json keys (app/clinic.py _VITAL_KEYS).
_LABELS = {"bp": "bp", "pulse": "pulse", "spo2": "spo2", "spo₂": "spo2", "temperature": "temp_f",
           "weight": "weight_kg", "height": "height_cm", "sugar": "sugar_mg_dl",
           "fasting sugar": "fasting_sugar_mg_dl", "non-fasting sugar": "nonfasting_sugar_mg_dl",
           "hb": "hb", "haemoglobin": "hb", "hemoglobin": "hb"}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def parse_reading(label: str, value: str) -> tuple[str, object] | None:
    """("BP", "130/80 mmHg") -> ("bp", "130/80"); ("SpO₂", "96%") -> ("spo2", 96.0).
    None for an unknown label or no number ("None mmHg")."""
    key = _LABELS.get(str(label).strip().lower())
    if key is None:
        return None
    if key == "bp":
        m = re.match(r"\s*(\d{2,3})\s*/\s*(\d{2,3})", str(value))
        return ("bp", f"{m[1]}/{m[2]}") if m else None
    m = _NUMBER.search(str(value))
    return (key, float(m[0])) if m else None


def vitals_by_visit(summary: dict) -> dict[str, dict]:
    """{visit_id: {"date", <vitals_json keys>...}} from /summary -> vitals."""
    out = {}
    for v in summary.get("vitals") or []:
        values = dict(filter(None, (parse_reading(r.get("label"), r.get("value")) for r in v.get("readings") or [])))
        if values:
            out[v["visit_id"]] = {"date": v.get("visit_date"), **values}
    return out


_FIELDS = {"chief complaint": "complaint", "provisional diagnosis": "provisional",
           "confirmed diagnosis": "confirmed", "prescription instructions": "instructions"}
_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z \-]*?)\s*(?:\([^)]*\))?\s*:\s*(.*)$")
_EMPTY = {"", "not documented", "none", "-", "—"}
_LAB = re.compile(r"^\s*•\s*([^:]+):\s*(.*?)\s*(?:\(Ref:.*?)?(?:\[([^\[\]]*(?:\([^)]*\))?)\])?\s*$")
# "• 2026-10-01 | MISSED", "• 2026-09-16 | COMPLETED → VISIT_COMPLETED"
_FOLLOWUP = re.compile(r"^\s*•\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([A-Z_]+)")
_PENDING = {"PENDING", "SCHEDULED"}  # the clinic DB's followup_schedule says PENDING


def followup_counts(entries: list[dict]) -> dict | None:
    """Follow-ups from every visit in the timeline, in app/clinic.py's shape:
    {pending, next_due, missed, last_missed, emergency}. None when the
    timeline lists no follow-ups. The timeline doesn't say which were
    emergencies, so that count is None."""
    items = [f for e in entries for f in e.get("followups") or []]
    if not items:
        return None
    pending = sorted(f["date"] for f in items if f["status"] in _PENDING)
    missed = sorted(f["date"] for f in items if f["status"] == "MISSED")
    return {"pending": len(pending), "next_due": pending[0] if pending else None,
            "missed": len(missed), "last_missed": missed[-1] if missed else None, "emergency": None}

# Lab results the reading rules use -> our vitals_json keys, with the unit
# they must be in. "Unverified" results are listed but never used by the rules.
_LAB_KEYS = {"haemoglobin": ("hb", "g/dl"), "hemoglobin": ("hb", "g/dl"), "hb": ("hb", "g/dl"),
             "fasting blood sugar": ("fasting_sugar_mg_dl", "mg/dl"), "fbs": ("fasting_sugar_mg_dl", "mg/dl"),
             "fasting glucose": ("fasting_sugar_mg_dl", "mg/dl"), "fasting plasma glucose": ("fasting_sugar_mg_dl", "mg/dl"),
             "random blood sugar": ("nonfasting_sugar_mg_dl", "mg/dl"), "rbs": ("nonfasting_sugar_mg_dl", "mg/dl"),
             "post prandial blood sugar": ("nonfasting_sugar_mg_dl", "mg/dl"), "ppbs": ("nonfasting_sugar_mg_dl", "mg/dl"),
             "random glucose": ("nonfasting_sugar_mg_dl", "mg/dl")}


def lab_readings(labs: list[dict]) -> dict:
    """The visit's lab results as vitals_json keys, for the reading rules:
    the worst value when a test was done twice (lowest Hb, highest sugar)."""
    out = {}
    for lab in labs:
        key, unit = _LAB_KEYS.get(lab["name"].strip().lower(), (None, None))
        m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(\S*)", lab["value"])
        if key is None or not m or m[2].lower() != unit or "unverified" in str(lab["status"]).lower():
            continue
        value = float(m[1])
        out[key] = min(out.get(key, value), value) if key == "hb" else max(out.get(key, value), value)
    return out


def parse_lab(line: str) -> dict | None:
    """"• Haemoglobin: 6.5 g/dL (Ref: 12 - 17.5 g/dL (...)) [Critical (Low)]"
    -> {"name": "Haemoglobin", "value": "6.5 g/dL", "status": "Critical (Low)"}."""
    m = _LAB.match(line)
    if not m:
        return None
    return {"name": m[1].strip(), "value": m[2].strip(), "status": m[3].strip() if m[3] else None}


def parse_timeline(text: str) -> list[dict]:
    """/timeline text -> one entry per visit, in the text's order (not always
    newest first: build_context sorts them):
    {"date", "visit_id", "complaint", "provisional", "confirmed", "instructions", "labs", "followups"}.
    A date can hold several visits ("Visit A of 2"); each starts at its VISIT ID.
    A field can run over several unindented lines ("DUB\\nPerimenopause"):
    they are joined with "; ". Lab results come from the visit's documents.
    Follow-ups come from the visit's "Follow-up Schedule" lines
    ("• 2026-10-01 | MISSED") as {"date", "status"}."""
    visits, day, current, field, in_labs, in_followups = [], None, None, None, False, False
    for line in str(text or "").splitlines():
        m = re.match(r"^\s*DATE:\s*(\d{4}-\d{2}-\d{2})", line)
        if m:
            day, current, field, in_labs, in_followups = m[1], None, None, False, False
            continue
        m = re.match(r"^\s*VISIT ID:\s*(\S+)", line)
        if m and day:
            current = {"date": day, "visit_id": m[1]}
            visits.append(current)
            field, in_labs, in_followups = None, False, False
            continue
        if in_followups and current is not None and (m := _FOLLOWUP.match(line)):
            current.setdefault("followups", []).append({"date": m[1], "status": m[2]})
            continue
        if field and line.strip() and not line[0].isspace() and not re.match(r"^[=\-]+$", line.strip()):
            more = line.strip().strip(",").strip()
            current[field] = "; ".join(filter(None, (current[field], more)))
            continue
        m = _LINE.match(line)
        name = m[1].strip().lower() if m else ""
        if in_labs and current is not None and (lab := parse_lab(line)):
            if lab not in current.setdefault("labs", []):  # the same report is often uploaded twice
                current["labs"].append(lab)
            continue
        in_labs = name.startswith("lab results")
        in_followups = name.startswith("follow-up schedule")
        field = _FIELDS.get(name) if day else None
        if field:
            if current is None:  # a timeline without VISIT ID lines
                current = {"date": day, "visit_id": None}
                visits.append(current)
            value = m[2].strip().strip(",").strip()
            current[field] = None if value.lower() in _EMPTY else value
    return visits


def _answered(history: dict, keys: tuple) -> list[dict]:
    out = []
    for key in keys:
        item = history.get(key) if isinstance(history, dict) else None
        if isinstance(item, dict) and item.get("present"):
            out.append({"item": key, "notes": (item.get("notes") or item.get("qty") or "").strip() or None})
    return out


def _sex(value) -> str | None:
    """As the clinic stores it (FEMALE / MALE / OTHER), which the screens expect."""
    return str(value).upper() if value else None


def _visits(summary: dict, timeline: str, names: dict[str, str],
            limit: int | None) -> tuple[list[dict], dict[str, dict], list[dict]]:
    """The visits, newest first, at most `limit` (None: all): (timeline
    entries, vitals by visit id, visits in app/clinic.py's shape)."""
    by_visit = vitals_by_visit(summary)
    meta = {v["visit_id"]: v for v in summary.get("visits") or []}
    entries = parse_timeline(timeline)
    if not entries:  # no timeline: the visits from /summary, without complaints or diagnoses
        entries = [{"date": v["visit_date"], "visit_id": v["visit_id"]} for v in summary.get("visits") or []]
    # Newest first, whatever order the timeline lists them in (some list the
    # oldest first); visits on the same date keep the timeline's order.
    entries = sorted(entries, key=lambda e: e["date"], reverse=True)[:limit]
    for e in entries:  # lab results count as readings, as the clinic DB's vitals do
        readings = lab_readings(e.get("labs") or [])
        if readings:
            vitals = by_visit.setdefault(e.get("visit_id"), {"date": e["date"]})
            for k, v in readings.items():
                if k not in vitals:  # a reading taken at the visit wins
                    vitals[k] = v
                    vitals.setdefault("from_lab", []).append(k)  # counts for longer (store.plans)

    visits = []
    for e in entries:
        m = meta.get(e.get("visit_id"), {})  # /summary lists the last 10 visits: older ones have no doctor
        vitals = {k: v for k, v in by_visit.get(e.get("visit_id"), {}).items() if k not in ("date", "from_lab")}
        visit = {"date": e["date"], "doctor": names.get(m.get("doctor_id")), "complaint": e.get("complaint"),
                 "vitals": vitals, "diagnosis_provisional": e.get("provisional"),
                 "diagnosis_confirmed": e.get("confirmed"), "patient_instructions": e.get("instructions"),
                 "labs": e.get("labs"), "emergency": m.get("is_emergency") or None}
        if m.get("is_referral_recommended"):
            visit["referral"] = {"to": m.get("referral_specialist_name"), "for": m.get("referral_treatment_name")}
        visits.append({k: v for k, v in visit.items() if v not in (None, "", [], {})})
    return entries, by_visit, visits


def build_context(summary: dict, timeline: str, doctor_names: dict[str, str] | None = None,
                  today: date | None = None) -> dict:
    """The patient record in app/clinic.py's patient_context() shape."""
    names = doctor_names or {}
    meta = {v["visit_id"]: v for v in summary.get("visits") or []}
    entries, by_visit, visits = _visits(summary, timeline, names, RECENT_VISITS)

    # Vitals: every visit /summary has them for, newest first.
    vitals_recent = sorted(by_visit.values(), key=lambda v: str(v["date"]), reverse=True)
    weight = next(((v["date"], v["weight_kg"]) for v in vitals_recent if v.get("weight_kg")), (None, None))
    height = next((v["height_cm"] for v in vitals_recent if v.get("height_cm")), None)
    bmi = round(weight[1] / (height / 100) ** 2, 1) if weight[1] and height and 100 <= height <= 230 else None

    recent_ids = {e.get("visit_id") for e in entries[:FLAG_VISITS]}
    flags = [{"date": f.get("date"), "metric": f.get("metric"), "code": f.get("code"),
              "severity": f.get("severity"), "value": f.get("value")}
             for f in summary.get("vital_flags") or [] if f.get("visit_id") in recent_ids]

    snap = summary.get("clinical_snapshot") or {}
    span = [s.strip() for s in str(snap.get("span") or "").split(" to ")]
    history = summary.get("health_history") or {}
    rx_with_diagnosis = [e for e in entries if e.get("provisional") or e.get("confirmed")]
    return {
        "patient": {"id": summary.get("patient_id"), "age": summary.get("age_years"), "sex": _sex(summary.get("sex")),
                    "language": None, "registered_on": None},
        "body": {"weight_kg": weight[1], "height_cm": height, "bmi": bmi, "measured_on": weight[0]},
        "conditions": {
            "doctor_recorded": [{k: c.get(k) for k in ("name", "severity", "status", "diagnosed_at")}
                                for c in summary.get("long_term_conditions") or []],
            "health_history": _answered(history, _HISTORY_CONDITIONS),
            "long_term_conditions": [],  # the API has the recorded list only (doctor_recorded)
            "recent_diagnoses": [{"date": e["date"], "provisional": e.get("provisional"),
                                  "confirmed": e.get("confirmed")} for e in rx_with_diagnosis],
        },
        "history_other": _answered(history, _HISTORY_OTHER),
        "vitals_recent": vitals_recent[:RECENT_VISITS],
        "vital_flags": flags,
        "visits": visits,
        "medicines": {"from": entries[0]["date"] if entries else None,
                      "items": [{"name": m} for m in summary.get("ongoing_medicines") or []],
                      "patient_instructions": entries[0].get("instructions") if entries else None,
                      "follow_up_at": None},
        "care": {"visits": snap.get("encounters"), "first_visit": span[0] or None,
                 "last_visit": span[-1] if len(span) > 1 else None,
                 "recent_complaints": [{"date": e["date"], "complaint": e["complaint"], "duration": None,
                                        "doctor": names.get(meta.get(e.get("visit_id"), {}).get("doctor_id"))}
                                       for e in entries if e.get("complaint")],
                 # every visit's follow-ups, not only the latest 10 visits'
                 "followups": followup_counts(parse_timeline(timeline)), "open_episodes": [], "open_tasks": []},
        "alerts": {
            "emergencies": [{"date": v["date"], "diagnosis": v.get("diagnosis_confirmed") or v.get("diagnosis_provisional")}
                            for v in visits if v.get("emergency")],
            "referrals": [{"date": v["date"], **v["referral"]} for v in visits if v.get("referral")],
        },
        "labs": [{"date": e["date"], **lab} for e in entries for lab in e.get("labs") or []],
        "clinical_summary": {"exercise_suitable": summary.get("exercise_suitable"), "patient_type": summary.get("patient_type"),
                "exercise_reason": summary.get("exercise_reason"),
                "flags": [{k: f.get(k) for k in ("level", "title", "evidence")}
                          for f in snap.get("flags") or [] if f.get("level") in ("high", "medium")]},
        "as_of": today or date.today(),
    }


# ── The five functions app/clinic.py has ────────────────────────────────────

def _doctors() -> list[dict]:
    return (_cached("/doctors") or {}).get("doctors", [])


def doctors() -> list[dict]:
    """Doctors who have seen at least one patient, busiest first."""
    return [{"id": d["doctor_id"], "name": d.get("name") or None, "specialization": None,
             "patients": d.get("patients")} for d in _doctors()]


def doctor_name(doctor_id: str) -> str | None:
    try:
        return next((d.get("name") for d in _doctors() if d["doctor_id"] == doctor_id), None)
    except patient_api.PatientApiError:
        return None


def patient_doctors(patient_id: str) -> list[dict]:
    """The doctors who saw this patient, most visits first. From /summary,
    which lists the last 10 visits only; it's the call opening the patient
    makes anyway (cached), so picking a doctor then opening costs one call.
    Empty for an unknown id or a child."""
    summary = _cached(f"/patients/{patient_id}/summary")
    if summary is None:
        return []
    _remember(patient_id, summary.get("age_years"), summary.get("sex"))
    if (summary.get("age_years") or 0) < MIN_AGE:
        return []
    try:
        names = {d["doctor_id"]: d.get("name") for d in _doctors()}
    except patient_api.PatientApiError:
        names = {}
    seen = {}
    for v in summary.get("visits") or []:
        if v.get("doctor_id"):
            d = seen.setdefault(v["doctor_id"], {"id": v["doctor_id"], "name": names.get(v["doctor_id"]),
                                                 "visits": 0, "last_visit": None})
            d["visits"] += 1
            d["last_visit"] = max(d["last_visit"] or "", str(v.get("visit_date") or "")) or None
    return sorted(seen.values(), key=lambda d: (-d["visits"], d["name"] or ""))


def patient_briefs(ids: list[str]) -> dict[str, dict]:
    """Age and sex for the review queue (a handful of patients waiting for a
    doctor), by id: one /demographics call per patient not already known.
    Never /summary."""
    out = {}
    for pid in dict.fromkeys(ids):
        try:
            person = _demographics(pid)
        except patient_api.PatientApiError:
            person = None
        if person:
            out[pid] = person
    return out


def patients(doctor_id: str | None, search: str, limit: int, min_visits: int,
             min_age: int = MIN_AGE) -> list[dict]:
    """A doctor's patients (or, with no doctor, the busiest doctor's), most
    recently seen first: one API call, the list itself. No call per patient
    (neither /summary nor /demographics): age and sex show for patients
    already known (opened, or in the review queue, in the last day), health
    history for those opened in the last few minutes, "?" otherwise. Known
    children are left out, and opening a child's record is refused
    (patient_context)."""
    search = search.strip().lower()
    params = {"limit": 200, **({"q": search} if search else {})}
    seen, rows = set(), []
    for d in ([{"doctor_id": doctor_id}] if doctor_id else _doctors()[:1]):
        for p in (_cached(f"/doctors/{d['doctor_id']}/patients", **params) or {}).get("patients", []):
            if p["patient_id"] not in seen and (p.get("visits") or 0) >= min_visits:
                seen.add(p["patient_id"])
                rows.append(p)
    rows.sort(key=lambda p: str(p.get("last_visit") or ""), reverse=True)
    out = []
    for p in rows:
        person, s = _known(p["patient_id"]), _cached_summary(p["patient_id"])
        if person and person["age"] is not None and person["age"] < min_age:
            continue
        out.append({"id": p["patient_id"], "age": person["age"] if person else None,
                    "sex": person["sex"] if person else None, "visits": p.get("visits"),
                    "last_visit": p.get("last_visit"),
                    "history": sorted(h["item"] for h in _answered((s or {}).get("health_history") or {},
                                                                   _HISTORY_CONDITIONS))})
        if len(out) >= limit:
            break
    return out


def patient_context(patient_id: str) -> dict | None:
    """What the agent knows about one patient: /summary + /timeline."""
    summary = _cached(f"/patients/{patient_id}/summary")
    if summary is None:
        return None
    _remember(patient_id, summary.get("age_years"), summary.get("sex"))
    if (summary.get("age_years") or 0) < MIN_AGE:
        return None  # the agent is for adults only
    return build_context(summary, _timeline(patient_id), _doctor_names())


def visit_history(patient_id: str) -> list[dict] | None:
    """Every visit, newest first, in patient_context()'s "visits" shape: for
    the doctor's visit-history picker. Screen only, never sent to the AI.
    From the /summary and /timeline the opened record already fetched
    (cached), so no extra call. None for an unknown patient or a child."""
    summary = _cached(f"/patients/{patient_id}/summary")
    if summary is None or (summary.get("age_years") or 0) < MIN_AGE:
        return None
    return _visits(summary, _timeline(patient_id), _doctor_names(), None)[2]


def _timeline(patient_id: str) -> str:
    return (_cached(f"/patients/{patient_id}/timeline") or {}).get("timeline", "")


def _doctor_names() -> dict[str, str]:
    try:
        return {d["doctor_id"]: d.get("name") for d in _doctors()}
    except patient_api.PatientApiError:
        return {}
