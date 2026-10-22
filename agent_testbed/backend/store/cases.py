"""Doctor cases: what the agent passed to a doctor."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from store.models import Case

log = logging.getLogger("agent.cases")

URGENCY_RANK = {"routine": 0, "priority": 1, "emergency": 2}


def open_case(db: Session, patient_id: str) -> Case | None:
    return db.scalars(select(Case).where(Case.patient_id == patient_id, Case.status == "open")
                      .order_by(Case.created_at.desc()).limit(1)).first()


def upsert_case(db: Session, patient_id: str, urgency: str, reason: str, summary: str,
                triggers: list[str]) -> Case:
    """One open case per patient; a new hand-off adds to it, never lowers urgency."""
    case = open_case(db, patient_id)
    if case is None:
        case = Case(patient_id=patient_id, urgency=urgency, reason=reason, summary=summary, triggers=triggers)
        db.add(case)
        db.flush()
        log.warning("New %s case %s", urgency, case.id)  # ids only: no health data in logs
        return case
    if URGENCY_RANK[urgency] > URGENCY_RANK[case.urgency]:
        case.urgency = urgency
    case.reason = reason
    stamp = datetime.now(timezone.utc).strftime("%d %b %H:%M UTC")
    case.summary = f"{case.summary}\n\nUpdate {stamp}: {summary}"
    case.triggers = sorted(set(case.triggers or []) | set(triggers))
    return case


def close_case(case: Case, doctor_id: str, note: str | None) -> None:
    case.status, case.closed_by, case.close_note = "closed", doctor_id, note


def case_dict(case: Case | None) -> dict | None:
    if case is None:
        return None
    return {"id": case.id, "status": case.status, "urgency": case.urgency, "reason": case.reason,
            "summary": case.summary, "triggers": case.triggers, "opened_on": case.created_at.date().isoformat()}
