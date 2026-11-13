"""The assessment: what is the patient's problem, and must a doctor write the
plan? Run when a doctor clicks "Generate plan" (BUILD_PLAN.md, phase 4).

  1. rules     agent.conditions: aliases and warning complaints (data, no AI)
  2. AI        reads the same record, picks codes from the reference list,
               quoting the record for each
  3. checks    an AI code outside the list, or a quote not in the record, is
               dropped (and kept in `dropped` for audit)
  4. safety    agent.routing.finalize: the rules decide severity; the AI can
               only add conditions and raise it
  5. saved     store.models.Assessment

If the AI fails, the rules' result is used alone; with nothing found, a
doctor decides.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agent.conditions import Finding, RuleResult, has_phrase, is_recent, load_reference, rule_findings, words
from agent.llm import MODEL, chat_model
from agent.prompts import ASSESS
from agent.routing import finalize
from app.source import clinic
from store import assessments as assessment_store
from store import plans as plan_store
from store.db import session
from store.models import Assessment

log = logging.getLogger("agent.assess")


class AIFinding(BaseModel):
    code: str
    quote: str = Field(description="Words copied exactly from PATIENT_RECORD")
    where: str = Field(description='Visit date and field, e.g. "visit 2026-10-10, diagnosis"')


class AIAssessment(BaseModel):
    conditions: list[AIFinding]
    problem: str
    body_area: str
    severity: Literal["mild", "moderate", "severe"]
    concerns: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


def _record(context: dict) -> dict:
    """What the AI reads: the clinical facts only."""
    return {"patient": {k: context["patient"][k] for k in ("age", "sex")}, "body": context["body"],
            "recorded_conditions": context["conditions"]["doctor_recorded"],
            "condition_list": context["conditions"]["long_term_conditions"],
            "health_history": context["conditions"]["health_history"], "history_other": context["history_other"],
            "visits": context["visits"], "vital_flags": context["vital_flags"], "alerts": context["alerts"]}


def _strings(value) -> list[str]:
    """Every field name and value, so a quote like "bp: 144/82" is found."""
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (str(k), *_strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return [str(value)] if value is not None else []


def _ask_ai(record: dict, ref, rules: RuleResult, today: date) -> AIAssessment:
    conditions = "\n".join(f"- {code}: {c['name']}" + (f" ({c['notes']})" if c["notes"] else "")
                           for code, c in ref.conditions.items() if code != "none")
    # bp_any / diabetes_any are the rules' "controlled or not, to be decided" markers.
    shown = {"bp_any": "blood pressure (controlled or not: decided from vital flags)",
             "diabetes_any": "diabetes (controlled or not: decided from vital flags)",
             "asthma_any": "asthma (controlled or not: decided by the rules)"}
    found = "\n".join(sorted({f"- {shown.get(f.code, f.code)}: {f.where}: \"{f.quote}\""
                              for f in rules.findings})) or "- nothing"
    windows = ", ".join(f"{code} {days}" for (code, src), days in sorted(ref.windows.items())
                        if src == "diagnosis" and days) or "none"
    prompt = ASSESS.format(today=today.isoformat(), conditions=conditions, found=found, windows=windows,
                           complaint_days=ref.complaint_days())
    model = chat_model(temperature=0, max_tokens=1500).with_structured_output(AIAssessment)
    return model.invoke([SystemMessage(content=prompt),
                         HumanMessage(content="PATIENT_RECORD\n" + json.dumps(record, ensure_ascii=False, default=str))])


# Whether BP or sugar is under control is the clinic's vital flags' call, not
# the AI's: an AI "not controlled" stands only when the record itself says so.
_FLAGS_DECIDE = {"high_bp": "bp_any", "diabetes": "diabetes_any", "asthma_uncontrolled": "asthma_any"}
_SAYS_UNCONTROLLED = re.compile(r"uncontrol|not (under )?control|poor(ly)? control|urgency|crisis|exacerbation",
                                re.I)


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _too_old(f: AIFinding, ref, today: date | None) -> int | None:
    """The time window (days) an AI finding is older than, by the visit date
    in its `where`; None when it counts (no window, no date, or recent)."""
    if today is None or not (m := _DATE.search(f.where)):
        return None
    days = ref.complaint_days(f.code) if "complaint" in f.where.lower() else ref.diagnosis_days(f.code)
    return days if days is not None and not is_recent(m[0], today, days) else None


def _check(ai: AIAssessment, ref, record: dict, today: date | None = None) -> tuple[list[Finding], list[dict], list[str]]:
    """Keep AI findings with a known code and a quote that is really in the
    record, within the code's time window (data/time_windows.csv). Returns
    (kept, dropped, concerns): an AI "not listed" finding becomes a concern
    for the doctor, not a reason on its own to stop the plan."""
    record_words = words(" | ".join(_strings(record)))
    kept, dropped, concerns = [], [], []
    for f in ai.conditions:
        if (f.code not in ref.conditions and f.code not in ("bp_any", "diabetes_any", "asthma_any")) \
                or f.code == "none":
            dropped.append({**f.model_dump(), "why": "not a code in the reference list"})
        elif not has_phrase(record_words, words(f.quote)):
            dropped.append({**f.model_dump(), "why": "quote not found in the record"})
        elif (days := _too_old(f, ref, today)) is not None:
            dropped.append({**f.model_dump(), "why": f"older than its {days}-day time window"})
        elif f.code == "other_unlisted":
            concerns.append(f"Not in our exercise list: \"{f.quote}\" ({f.where})")
        else:
            code = f.code if _SAYS_UNCONTROLLED.search(f.quote) else _FLAGS_DECIDE.get(f.code, f.code)
            kept.append(Finding(code, "ai", f.where, f.quote, "complaint" in f.where.lower()))
    return kept, dropped, concerns

_MISSING_READING = {"bp": re.compile(r"\b(blood pressure|bp)\b", re.I),
                    "sugar": re.compile(r"\b(sugar|glucose)\b", re.I)}

def _drop_known_missing(missing: list[str], readings: dict) -> list[str]:
    have = {k for k in _MISSING_READING if readings.get(k) and not readings[k].get("older")}
    return [m for m in missing if not any(_MISSING_READING[k].search(m) for k in have)]


def run_assessment(patient_id: str, doctor_id: str, today: date | None = None,
                   context: dict | None = None, reading_days: int = plan_store.READING_DAYS) -> dict:
    """`reading_days` above the default: the doctor included older readings."""
    today = today or date.today()
    context = context or clinic.patient_context(patient_id)
    if context is None:
        raise ValueError("Patient not found")
    with session() as db:
        ref = load_reference(db)
    rules = rule_findings(context, ref, today)
    record = _record(context)

    windows = {m: ref.windows.get((m, "reading")) or d for m, d in plan_store.READING_WINDOWS.items()}
    readings = plan_store.latest_readings(context["vitals_recent"], today, reading_days, windows)


    ai, ai_findings, dropped, unlisted = None, [], [], []
    try:
        answer = _ask_ai(record, ref, rules, today)
        ai_findings, dropped, unlisted = _check(answer, ref, record, today)
        ai = answer.model_dump()
    except Exception as exc:  # the rules' result stands on its own
        log.error("Assessment AI call failed for patient %s: %s", patient_id, exc)

    result = finalize(context, ref, rules, ai, ai_findings)
    with session() as db:
        saved = Assessment(
            patient_id=patient_id, doctor_id=doctor_id, codes=result["codes"], conditions=result["conditions"],
            severity=result["severity"], severe_reasons=result["severe_reasons"],
            problem=(ai or {}).get("problem", ""), body_area=(ai or {}).get("body_area", ""),
            concerns=[*result["concerns"], *(ai or {}).get("concerns", []), *unlisted], missing=_drop_known_missing((ai or {}).get("missing", []), readings),
            unmapped=rules.unmapped, warnings=rules.warnings, ai_status="ok" if ai else "failed",
            ai_output=ai, dropped=dropped, model=MODEL,
            readings={**readings, "days": reading_days, "windows": windows})
        db.add(saved)
        db.flush()
        return assessment_store.assessment_dict(saved, full=True)
