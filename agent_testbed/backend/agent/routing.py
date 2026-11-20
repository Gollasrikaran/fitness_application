"""Safety rules that decide, whatever the AI says. Plain code, no AI.

finalize() merges what the rules and the AI found and decides whether a
doctor must write the plan ("severe"). The rules can only escalate: the AI
can add conditions and raise the severity, never remove or lower them.
Which conditions need a doctor comes from the reference data (bucket
"refer"), not from code.
"""
from __future__ import annotations

import re

from agent.conditions import Finding, Reference, RuleResult, has_phrase, words
from datetime import date

from agent.conditions import is_recent
from store.plans import (ASSUMED_BP, READING_WINDOWS, SEVERE_THIN_BMI, UNDERWEIGHT_BMI, bp_of, latest_bp, latest_readings,
                         reading_text)


# The clinic's own vital flags (ELEVATED and LOW don't count as "not under control").
_SUGAR_FLAG = re.compile(r"SUGAR_MG_DL_(HIGH|CRITICAL)$")
_SUGAR_KEYS = ("sugar_mg_dl", "fasting_sugar_mg_dl", "nonfasting_sugar_mg_dl")
# The AI reports BP, sugar and asthma as "controlled" by default; the rules decide.
_TO_MARKER = {"bp_controlled": "bp_any", "diabetes_controlled": "diabetes_any", "asthma_controlled": "asthma_any"}
# Asthma not under control (research/ASTHMA.md, Part B point 4). No medicines.
_ASTHMA_COMPLAINTS = {"Breathlessness", "Wheeze"}  # warning-complaint labels, last 6 months
ASTHMA_SPO2_BELOW = 94
# Dizziness stops an AI draft only for higher-risk patients: age 60+, or BP,
# diabetes or a heart condition (decided 2026-11-05, KNOWN_ISSUES.md #7; needs
# clinical sign-off). For anyone else it is a concern the doctor sees.
DIZZINESS = "Dizziness"
DIZZINESS_STOP_AGE = 60
DIZZINESS_STOP_CODES = {"bp_controlled", "high_bp", "diabetes_controlled", "diabetes", "heart_condition"}
# Low BP (2026-11-13, provisional; QUESTIONS_FOR_DOCTOR.md 5.4): a reading
# below 90/60 limits the plan (data/reading_rules.csv); the clinic's LOW
# flags and a "hypotension" diagnosis are concerns the doctor sees.
_BP_LOW_FLAG = re.compile(r"^BP_(SYS|DIA)_LOW$")
_LOW_BP_WORDS = [words(p) for p in ("hypotension", "low bp", "low blood pressure")]


def _low_bp_concerns(context: dict) -> list[str]:
    out = [f"Clinic flagged low BP: {f['code']} on {f['date']}" + (f" ({f['value']})" if f.get("value") else "")
           + ". Check for dizziness on standing." for f in context["vital_flags"] if _BP_LOW_FLAG.match(f["code"])]
    for v in context["visits"]:
        for field, text in (("diagnosis", " / ".join(filter(None, (v.get("diagnosis_confirmed"),
                                                                   v.get("diagnosis_provisional"))))),
                            ("complaint", v.get("complaint") or "")):
            if text and any(has_phrase(words(text), p) for p in _LOW_BP_WORDS):
                out.append(f"Low BP in the {field} on {v['date']}: \"{text.strip()}\". Check for dizziness on standing.")
    return out


def _underweight(context: dict) -> tuple[list[str], list[str]]:
    """(severe reasons, concerns) from a low BMI."""
    body = context.get("body") or {}
    bmi = body.get("bmi")
    if bmi is None or bmi >= UNDERWEIGHT_BMI:
        return [], []
    measured = f" (measured {body['measured_on']})" if body.get("measured_on") else ""
    if bmi < SEVERE_THIN_BMI:
        return [f"BMI {bmi}{measured} is below {SEVERE_THIN_BMI:g} (severe thinness): a doctor writes the plan "
                "(provisional rule)"], []
    return [], [f"Underweight: BMI {bmi}{measured}. Check for weight loss or illness (provisional rule)."]


# With no reading, the safety decision stays "controlled" (BP's cautious
# default is in the reading rules), but the name says control isn't known.
_UNKNOWN_NAME = {"bp_controlled": "BP, control not known (no recent BP reading)",
                 "diabetes_controlled": "Diabetes, control not known (no recent sugar reading)"}


def _uncontrolled(visits: list[dict], flags: list[dict], flag: re.Pattern, keys: tuple, what: str,
                  today: date | None = None, days: int | None = None) -> tuple[bool | None, str]:
    """Not under control when the latest reading is flagged high, or any
    reading in the last 5 visits is critical. Returns (uncontrolled, why);
    uncontrolled is None when control is not known.
    A latest reading older than `days` (its window in data/time_windows.csv)
    counts only when high (decided 2026-11-16): old good news is not "under
    control", old bad news still is "not under control"."""
    critical = sorted({f"{f['code']} on {f['date']}" for f in flags
                       if flag.search(f["code"]) and f["severity"] == "CRITICAL"})
    if critical:
        return True, f"critical {what} reading: {', '.join(critical)}"
    latest = next((str(v["date"]) for v in visits if any(k in v.get("vitals", {}) for k in keys)), None)
    if latest is None:
        return None, f"no {what} reading in the recent visits, so whether it is under control is not known"
    old = today is not None and days is not None and not is_recent(latest, today, days)
    age = f", {(today - date.fromisoformat(latest[:10])).days} days ago: older than its {days}-day window" if old else ""
    high = sorted({f["code"] for f in flags if flag.search(f["code"]) and str(f["date"]) == latest})
    if high:
        return True, f"latest {what} reading ({latest}{age}) flagged {', '.join(high)}"
    if old:
        return None, f"latest {what} reading ({latest}{age}) not flagged high, so whether it is under control is not known"
    return False, f"latest {what} reading ({latest}) not flagged high; nothing critical in the last 5 visits"


# BP control from the average of the recent readings (fix 03, 2026-11-20;
# store.plans.latest_bp): below 140/90 under control; 140-159/90-99 above
# target (an AI draft, with the 140/90 reading limits); 160/100 or above, or
# a critical flag, not under control (a doctor writes the plan: ACSM asks
# for medical clearance from 160/100). One reading only: control not known.
BP_DOCTOR_AT = (160.0, 100.0)
_BP_CRITICAL = re.compile(r"^BP_(SYS|DIA)_CRITICAL$")


def _bp_control(context: dict, ref: Reference | None, today: date | None) -> tuple[bool | None, str, str | None]:
    """(not under control: True / False / None for not known, evidence line,
    the name to show instead of "BP under control", if any)."""
    critical = sorted({f"{f['code']} on {f['date']}" for f in context["vital_flags"]
                       if _BP_CRITICAL.match(f["code"]) and f["severity"] == "CRITICAL"})
    if critical:
        return True, f"critical BP reading: {', '.join(critical)}", None
    vitals = context.get("vitals_recent") or [{**v.get("vitals", {}), "date": v["date"]} for v in context["visits"]]
    days = (ref.windows.get(("bp", "reading")) if ref else None) or READING_WINDOWS["bp"]
    dates = sorted(str(v["date"])[:10] for v in vitals if v.get("date") and bp_of(v))
    if not dates:
        return None, "no BP reading in the recent visits, so whether it is under control is not known", None
    # No date to count from: the window counts back from the newest reading.
    today = today or date.fromisoformat(dates[-1])
    bp = latest_bp(vitals, today, windows={"bp": days})
    doctor = lambda s, d: s >= BP_DOCTOR_AT[0] or d >= BP_DOCTOR_AT[1]
    if bp is None:  # nothing within the window: an old reading counts only if it is very high
        old = latest_bp(vitals, today, days=10 ** 5, windows={"bp": days})
        if old and doctor(old["sys"], old["dia"]):
            return True, f"latest BP reading {reading_text('bp', old)}, older than {days} days, at or above 160/100", None
        return None, f"no BP reading in the last {days} days, so whether it is under control is not known", None
    s, d, text = bp["sys"], bp["dia"], reading_text("bp", bp)
    if doctor(s, d):
        return True, f"BP {text}: at or above 160/100", None
    if bp.get("count", 1) == 1:
        return None, f"only one BP reading in the last {days} days ({text}), so whether it is under control is not known", \
            f"BP, control not known (one reading in {days} days: {s:g}/{d:g})"
    readings = "; ".join(bp["readings"])
    if s >= ASSUMED_BP["sys"] or d >= ASSUMED_BP["dia"]:
        return False, f"BP {text}: above the 140/90 target, below 160/100 ({readings})", \
            f"BP above target (average {s:g}/{d:g} of {bp['count']} readings)"
    return False, f"BP {text}: below 140/90 ({readings})", None


def _resolve_markers(findings: list[Finding], context: dict, ref: Reference | None = None,
                     today: date | None = None) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """bp_any -> controlled or not from the average BP reading (_bp_control);
    diabetes_any from the clinic's vital flags. Returns (code, evidence line)
    per decision, and the names to show instead of the condition's own
    ("BP above target …", "control not known …")."""
    visits, flags = context["visits"], context["vital_flags"]
    notes, names = [], {}
    if any(f.code in ("bp_any", "high_bp", "bp_controlled") for f in findings):
        bad, why, name = _bp_control(context, ref, today)
        for f in findings:
            if f.code == "bp_any":
                f.code = "high_bp" if bad else "bp_controlled"
        notes.append(("high_bp" if bad else "bp_controlled", why))
        if bad is None:
            names["bp_controlled"] = name or _UNKNOWN_NAME["bp_controlled"]
        elif name:
            names["bp_controlled"] = name
    if any(f.code in ("diabetes_any", "diabetes", "diabetes_controlled") for f in findings):
        days = ((ref.windows.get(("sugar", "reading")) if ref else None) or READING_WINDOWS["sugar"]) if today else None
        bad, why = _uncontrolled(visits, flags, _SUGAR_FLAG, _SUGAR_KEYS, "sugar", today, days)
        for f in findings:
            if f.code == "diabetes_any":
                f.code = "diabetes" if bad else "diabetes_controlled"
        notes.append(("diabetes" if bad else "diabetes_controlled", why))
        if bad is None:
            names["diabetes_controlled"] = _UNKNOWN_NAME["diabetes_controlled"]
    return notes, names


def _latest_spo2(visits: list[dict], today: date | None = None, days: int | None = None
                 ) -> tuple[float, str, bool] | None:
    """The newest plausible SpO2 (50–100%) in the recent visits: (value,
    date, within its window). The window (`days` before `today`, from
    data/time_windows.csv) is the readings line's own (fix 05, 2026-11-20);
    with no `today`, every reading is within it."""
    for v in visits:
        try:
            value = float(str(v.get("vitals", {}).get("spo2", "")).rstrip("%").strip())
        except ValueError:
            continue
        if 50 <= value <= 100:
            day = str(v["date"])[:10]
            recent = today is None or days is None or is_recent(day, today, days)
            return value, day, recent
    return None


def _record_span(context: dict) -> tuple[str | None, str | None, int]:
    """(first visit date, last visit date, number of visit dates) of the record."""
    visits = context.get("visits_all") or context["visits"]
    dates = sorted({str(v["date"])[:10] for v in visits if v.get("date")})
    first = str((context.get("care") or {}).get("first_visit") or "")[:10] or (dates[0] if dates else None)
    return (min(first, dates[0]) if first and dates else first), (dates[-1] if dates else None), len(dates)


def _resolve_asthma(findings: list[Finding], context: dict, rules: RuleResult, ref: Reference | None = None,
                    today: date | None = None) -> tuple[list[tuple[str, str]], str | None]:
    """asthma_any -> asthma_controlled or asthma_uncontrolled. Not under
    control with breathlessness or wheeze in a complaint in the last 6 months,
    an emergency visit, or a latest SpO2 below 94%. Returns ((code, evidence
    line), the name to show instead of "Asthma under control", if any).
    "Under control" needs a record that covers the complaint window (6
    months) with 2 or more visit dates: a shorter record can't show 6 months
    without wheeze, so its asthma is "control not known" (fix 03,
    2026-11-20). The safety decision is the same either way."""
    if not any(f.code in ("asthma_any", "asthma_controlled", "asthma_uncontrolled") for f in findings):
        return [], None
    why = [f"{w['label'].lower()} in the complaint on {w['date']}" for w in rules.warnings
           if w["label"] in _ASTHMA_COMPLAINTS]
    why += [f"emergency visit on {e['date']}" for e in context["alerts"]["emergencies"]]
    first, last, count = _record_span(context)
    today = today or (date.fromisoformat(last) if last else None)
    # SpO2 within its window only (fix 05): an old low reading still counts,
    # as for BP (old bad news stands); an old normal one is never cited.
    spo2_days = (ref.windows.get(("spo2", "reading")) if ref else None) or READING_WINDOWS["spo2"]
    spo2 = _latest_spo2(context["visits"], today, spo2_days)
    if spo2 and spo2[0] < ASTHMA_SPO2_BELOW:
        why.append(f"SpO2 {spo2[0]:g}% on {spo2[1]}" + ("" if spo2[2] else f" (older than {spo2_days} days)"))
    code = "asthma_uncontrolled" if why else "asthma_controlled"
    for f in findings:
        if f.code == "asthma_any":
            f.code = code
    if why:
        return [(code, "not under control: " + "; ".join(dict.fromkeys(why)))], None
    window = ref.complaint_days() if ref else 183
    short = not first or count < 2 or (today is not None and (today - date.fromisoformat(first)).days < window)
    span = f"{count} visit{'s' if count != 1 else ''}, {first} to {last}" if first and first != last \
        else f"1 visit, {last}" if last else "no visits"
    rest = ", no emergency visit, " + (f"SpO2 {spo2[0]:g}% on {spo2[1]}" if spo2 and spo2[2]
                                       else f"no SpO2 reading in the last {spo2_days} days")
    if short:
        return [(code, f"no breathlessness or wheeze in the record ({span}){rest}; the record is too short to "
                       f"show {window // 30} months without symptoms")], \
            f"Asthma, control not known (record: {span})"
    return [(code, f"no breathlessness or wheeze in the last {window // 30} months{rest}")], None


# Thyroid (research/THYROID.md, 2026-11-18; provisional). "Thyroid" with the
# type not recorded (thyroid_any) is treated as underactive, the far more
# common one, unless the latest resting pulse is THYROID_FAST_PULSE or above
# (the ATA's beta-blocker threshold): then possibly overactive, a doctor
# writes the plan. Overactive wording anywhere wins over underactive.
THYROID_FAST_PULSE = 90
THYROID_GUESS_NAME = "Thyroid problem (type not recorded; treated as underactive)"
_THYROID = ("thyroid_any", "hypothyroid", "hyperthyroid")


def _latest_pulse(context: dict, ref: Reference | None, today: date | None) -> dict | None:
    """The newest resting pulse within its window: {"value", "date"}, or None."""
    vitals = context.get("vitals_recent") or [{**v.get("vitals", {}), "date": v["date"]} for v in context["visits"]]
    days = (ref.windows.get(("pulse", "reading")) if ref else None) or READING_WINDOWS["pulse"]
    return latest_readings(vitals, today or date.today(), windows={"pulse": days})["pulse"]


def _resolve_thyroid(findings: list[Finding], context: dict, ref: Reference | None,
                     today: date | None) -> tuple[list[tuple[str, str]], bool]:
    """thyroid_any -> hypothyroid or hyperthyroid. Returns (code, evidence
    line) per decision, and whether "underactive" is only a guess (no record
    says which)."""
    codes = {f.code for f in findings}
    if not codes & set(_THYROID):
        return [], False
    if "hyperthyroid" in codes:
        code, why = "hyperthyroid", ("overactive thyroid in the record, so the stricter reading wins"
                                     if codes & {"thyroid_any", "hypothyroid"} else None)
    else:
        pulse = _latest_pulse(context, ref, today) if "thyroid_any" in codes else None
        if pulse and pulse["value"] >= THYROID_FAST_PULSE:
            code, why = "hyperthyroid", (f"thyroid type not recorded and resting pulse {pulse['value']:g}/min on "
                                         f"{pulse['date']} is {THYROID_FAST_PULSE} or above: possibly overactive")
        else:
            code, why = "hypothyroid", None
    for f in findings:
        if f.code in _THYROID:
            f.code = code
    guessed = code == "hypothyroid" and "hypothyroid" not in codes
    if guessed:
        why = "thyroid type not recorded: treated as underactive (" + (
            "no resting pulse in the recent visits)" if not _latest_pulse(context, ref, today)
            else f"resting pulse below {THYROID_FAST_PULSE}/min)")
    return ([(code, why)] if why else []), guessed


# The AI sometimes names the record's raw fields in `where` ("visit 2026-10-01,
# diagnosis_provisional"): shown as the rules word them.
_WHERE_WORDS = {"diagnosis_provisional": "diagnosis", "diagnosis_confirmed": "diagnosis",
                "recorded_conditions": "doctor recorded", "chief_complaint": "complaint"}
_WHERE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _tidy_where(where: str) -> str:
    return re.sub("|".join(_WHERE_WORDS), lambda m: _WHERE_WORDS[m[0]], where)


def _field(where: str) -> str:
    """"visit 2026-10-01, complaint" -> "complaint"; "" when no visit field is named."""
    m = re.search(r"\b(complaint|diagnosis|medicines?)\b", where, re.I)
    return m[1].lower().rstrip("s") if m else ""


def _same_evidence(where: str, quote: str, other_where: str, other_quote: str) -> bool:
    """The same fact said twice (the rules found it, then the AI): the same
    date (or both undated) and one quote inside the other. E.g. "BMI measured
    2026-10-01" and "measured on 2026-10-01", both "BMI 30.8"; or the AI
    quoting part of a complaint the rules quoted whole."""
    d1, d2 = _WHERE_DATE.search(where), _WHERE_DATE.search(other_where)
    if (d1 and d1[0]) != (d2 and d2[0]):
        return False
    if _field(where) != _field(other_where):  # a complaint never repeats a diagnosis
        return False
    # Undated: the same source, ignoring the detail the AI adds after a comma
    # ("health history" and "health history, hypertension", 6959e408 on 2026-11-18).
    source = lambda w: w.split(",")[0].strip().lower()
    if not d1 and source(where) != source(other_where):
        return False
    # Word by word, as the quote check reads them: "HTN,DM" and "HTN-DM" are the same words.
    a, b = words(quote), words(other_quote)
    return bool(a and b) and (has_phrase(a, b) or has_phrase(b, a))


def finalize(context: dict, ref: Reference, rules: RuleResult, ai: dict | None,
             ai_findings: list[Finding], today: date | None = None) -> dict:
    """`today`: for the readings' windows in "under control" (default: the
    record's as_of; with neither, the latest reading counts however old)."""
    findings = [*rules.findings, *ai_findings]
    for f in findings:
        f.code = _TO_MARKER.get(f.code, f.code)
    # A clinic condition we can't map: a doctor decides.
    findings += [Finding("other_unlisted", "rules", u, u) for u in rules.unmapped]
    flag_notes, names = _resolve_markers(findings, context, ref, today or context.get("as_of"))
    asthma_notes, asthma_name = _resolve_asthma(findings, context, rules, ref, today or context.get("as_of"))
    flag_notes += asthma_notes
    if asthma_name:
        names["asthma_controlled"] = asthma_name
    thyroid_notes, thyroid_guessed = _resolve_thyroid(findings, context, ref, today or context.get("as_of"))
    flag_notes += thyroid_notes

    # The stricter reading wins: "controlled" evidence joins the uncontrolled
    # code, so the doctor still sees it (and the flags note below says why).
    codes = {f.code for f in findings}
    if "asthma_uncontrolled" in codes:
        for f in findings:
            if f.code == "asthma_controlled":
                f.code = "asthma_uncontrolled"
        flag_notes = [(c, n) for c, n in flag_notes if c != "asthma_controlled"]
    for strict, mild, flag_kind in (("high_bp", "bp_controlled", "BP"), ("diabetes", "diabetes_controlled", "sugar")):
        if strict in codes:
            for f in findings:
                if f.code == mild:
                    f.code = strict
            if any(code == mild for code, _ in flag_notes):  # the rules said controlled: the AI raised it
                flag_notes = [(code, note) for code, note in flag_notes if code != mild]
                flag_notes.append((strict, f"not under control is the AI's judgement: the {flag_kind} "
                                           f"{'readings' if flag_kind == 'BP' else 'flags'} say controlled"))

    grouped: dict[str, dict] = {}
    for f in findings:
        name = (names[f.code] if f.code in names
                else THYROID_GUESS_NAME if f.code == "hypothyroid" and thyroid_guessed
                else ref.conditions[f.code]["name"])
        g = grouped.setdefault(f.code, {"code": f.code, "name": name,
                                        "bucket": ref.conditions[f.code]["bucket"], "found_by": set(),
                                        "complaint_only": True, "evidence": []})
        g["found_by"].add(f.found_by)
        g["complaint_only"] &= f.complaint_only
        where = _tidy_where(f.where)
        seen = g.setdefault("_seen", [])
        # Only the AI's repeat of a line is dropped: every rules line is kept.
        if f.found_by == "rules" or not any(_same_evidence(where, f.quote, w, q) for w, q in seen):
            seen.append((where, f.quote))
            line = f"{where}: \"{f.quote}\""
            if line not in g["evidence"]:
                g["evidence"].append(line)
    for code, note in flag_notes:
        if code in grouped:
            grouped[code]["evidence"].append(note)
    conditions = sorted(grouped.values(), key=lambda g: (g["bucket"] != "refer", g["code"]))
    for g in conditions:
        g["found_by"] = " + ".join(sorted(g["found_by"]))
        g.pop("_seen", None)

    reasons = [f"{g['name']} ({g['code']}) needs a doctor" for g in conditions if g["bucket"] == "refer"]
    reasons += [f"Critical vital: {f['code']} = {f['value']} on {f['date']}"
                for f in context["vital_flags"] if f["severity"] == "CRITICAL"]
    reasons += [f"Recorded by a doctor as severe: {c['name']}" for c in context["conditions"]["doctor_recorded"]
                if str(c.get("severity") or "").upper() == "SEVERE"]
    reasons += [f"Emergency visit on {e['date']}" for e in context["alerts"]["emergencies"]]
    age = (context.get("patient") or {}).get("age")
    dizziness_stops = (age is not None and age >= DIZZINESS_STOP_AGE) or bool(DIZZINESS_STOP_CODES & set(grouped))
    concerns = []
    for w in rules.warnings:
        line = f"{w['label']} in the complaint on {w['date']}: \"{w['complaint']}\""
        if w["label"] == DIZZINESS and not dizziness_stops:
            concerns.append(f"{line}. Not a stop on its own: under 60, with no BP, diabetes or heart condition. "
                            "Please check it has passed.")
        else:
            reasons.append(line)
    thin_reasons, thin_concerns = _underweight(context)
    reasons += thin_reasons
    concerns += thin_concerns + _low_bp_concerns(context)
    # Left out as older than their time window (data/time_windows.csv): the doctor still sees them.
    concerns += [f"Not counted, too old: {line}" for line in rules.expired]
    if ai is None and not conditions:
        reasons.append("Assessment incomplete: the AI was unavailable and the rules found no condition")
    if ai is not None and ai["severity"] == "severe":
        reasons.append(f"AI rated it severe: {ai['problem']}")

    reasons = list(dict.fromkeys(reasons))  # the clinic can hold the same flag twice
    severity = "severe" if reasons else (ai["severity"] if ai is not None else "moderate")
    return {"codes": [g["code"] for g in conditions] or ["none"], "conditions": conditions,
            "severity": severity, "severe_reasons": reasons, "concerns": list(dict.fromkeys(concerns))}
