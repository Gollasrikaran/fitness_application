"""Clinic record -> our condition codes, by fixed data (no AI).

The conditions (code, name, bucket) come from the reference data, and how
the clinic writes each one from data/condition_aliases.csv. This module only
matches; it holds no condition lists of its own. Sources:

- the clinic's long-term condition list and the patient's own list (exact name)
- the health-history questionnaire (item key)
- diagnoses from every visit we have (phrase, as whole words)
- chief complaints from visits in the last RECENT_DAYS (phrase, as whole
  words). A complaint is a symptom, not a diagnosis: those findings are
  marked complaint_only so the doctor sees they are a best match.

How long each finding counts is in data/time_windows.csv (e.g. a fresh
injury 90 days, complaints about 6 months; empty: however old). A finding
older than its window is left out and listed in `expired` for the doctor.

A clinic condition or questionnaire item with no alias is reported as
unmapped, never dropped. PROVISIONAL: the alias file needs clinical review,
like the safety grid.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from store.models import Condition, ConditionAlias, TimeWindow, WarningComplaint

RECENT_DAYS = 183  # default: chief complaints older than about 6 months may have resolved (data/time_windows.csv)
OBESE_BMI = 30


@dataclass
class Reference:
    conditions: dict[str, dict]  # code -> {name, bucket, notes}
    aliases: list[ConditionAlias]
    warnings: list[WarningComplaint]
    # (what, counts_from) -> days, None = no limit (data/time_windows.csv)
    windows: dict[tuple[str, str], int | None] = field(default_factory=dict)

    def complaint_days(self, code: str | None = None) -> int:
        """How long a complaint counts: the condition's own complaint row, else
        "any" (or "warning" for warning complaints), else RECENT_DAYS; never
        longer than the condition's diagnosis window."""
        days = self.windows.get((code, "complaint")) if code else None
        days = days or self.windows.get(("warning" if code == "warning" else "any", "complaint")) or RECENT_DAYS
        limit = self.windows.get((code, "diagnosis")) if code else None
        return min(days, limit) if limit else days

    def diagnosis_days(self, code: str) -> int | None:
        """How long a diagnosis counts; None: however old."""
        return self.windows.get((code, "diagnosis"))


@dataclass
class Finding:
    code: str
    found_by: str  # rules | ai
    where: str  # e.g. "visit 2026-10-10, diagnosis"
    quote: str  # the record's own words
    complaint_only: bool = False


@dataclass
class RuleResult:
    findings: list[Finding] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)  # clinic conditions we have no alias for
    warnings: list[dict] = field(default_factory=list)  # [{label, date, complaint}]
    expired: list[str] = field(default_factory=list)  # findings left out as older than their time window


def load_reference(db: Session) -> Reference:
    return Reference(
        conditions={c.code: {"name": c.display_name, "bucket": c.bucket, "notes": c.notes}
                    for c in db.scalars(select(Condition).order_by(Condition.display_order))},
        aliases=list(db.scalars(select(ConditionAlias))),
        warnings=list(db.scalars(select(WarningComplaint))),
        windows={(w.what, w.counts_from): w.days for w in db.scalars(select(TimeWindow))})


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def has_phrase(text_words: list[str], phrase_words: list[str]) -> bool:
    """The phrase appears in the text as whole words, in order."""
    n = len(phrase_words)
    return n > 0 and any(text_words[i:i + n] == phrase_words for i in range(len(text_words) - n + 1))


def is_recent(day, today: date, days: int = RECENT_DAYS) -> bool:
    day = date.fromisoformat(str(day)[:10]) if day else None
    return day is not None and day >= today - timedelta(days=days)


def rule_findings(context: dict, ref: Reference, today: date | None = None) -> RuleResult:
    today = today or date.today()
    named = {a.phrase.strip().lower(): a.code for a in ref.aliases if a.source == "long_term_condition"}
    history = {a.phrase.strip().lower(): a.code for a in ref.aliases if a.source == "health_history"}
    phrases = [(words(a.phrase), a.code) for a in ref.aliases if a.source == "text"]
    warnings = [(words(w.phrase), w.label) for w in ref.warnings]
    out = RuleResult()

    def match_text(text: str, day, where: str, complaint: bool) -> None:
        text_words = words(text)
        for phrase_words, code in phrases:
            if has_phrase(text_words, phrase_words):
                days = ref.complaint_days(code) if complaint else ref.diagnosis_days(code)
                if days is not None and day and not is_recent(day, today, days):  # no date: it counts
                    line = f"{ref.conditions.get(code, {}).get('name', code)}: {where} (\"{text.strip()}\"), " \
                           f"older than {days} days"
                    if line not in out.expired:
                        out.expired.append(line)
                    continue
                out.findings.append(Finding(code, "rules", where, text.strip(), complaint))

    conds = context["conditions"]
    listed = ([(c["name"], "doctor recorded") for c in conds["doctor_recorded"]]
              + [(name, "patient's condition list") for name in conds["long_term_conditions"]])
    for name, where in listed:
        code = named.get(str(name).strip().lower())
        if code:
            out.findings.append(Finding(code, "rules", where, name))
        elif f"{where}: {name}" not in out.unmapped:
            out.unmapped.append(f"{where}: {name}")
    for h in conds["health_history"]:
        code = history.get(h["item"])
        if code:
            out.findings.append(Finding(code, "rules", "health history", h["item"]))
        else:
            out.unmapped.append(f"health history: {h['item']}")

    # Every visit we have (visits_all: the API's whole timeline), each finding
    # within its time window; the AI reads only the latest visits.
    for v in context.get("visits_all") or context["visits"]:
        diagnosis = " / ".join(filter(None, (v.get("diagnosis_confirmed"), v.get("diagnosis_provisional"))))
        if diagnosis:
            match_text(diagnosis, v["date"], f"visit {v['date']}, diagnosis", complaint=False)
        complaint = v.get("complaint")
        if complaint and is_recent(v["date"], today, ref.complaint_days()):
            match_text(complaint, v["date"], f"visit {v['date']}, complaint", complaint=True)
        if complaint and is_recent(v["date"], today, ref.complaint_days("warning")):
            complaint_words = words(complaint)
            for phrase_words, label in warnings:
                if has_phrase(complaint_words, phrase_words):
                    out.warnings.append({"label": label, "date": str(v["date"]), "complaint": complaint.strip()})

    bmi = context["body"].get("bmi")
    if bmi and bmi >= OBESE_BMI:
        out.findings.append(Finding("obesity", "rules", f"BMI measured {context['body'].get('measured_on')}", f"BMI {bmi}"))
    return out
