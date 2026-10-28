"""Saved assessments (store.models.Assessment)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from store.models import Assessment


def latest(db: Session, patient_id: str) -> Assessment | None:
    return db.scalars(select(Assessment).where(Assessment.patient_id == patient_id)
                      .order_by(Assessment.created_at.desc()).limit(1)).first()


def assessment_dict(a: Assessment | None, full: bool = False) -> dict | None:
    if a is None:
        return None
    out = {"id": a.id, "codes": a.codes, "conditions": a.conditions, "severity": a.severity,
           "severe_reasons": a.severe_reasons, "problem": a.problem, "body_area": a.body_area,
           "concerns": a.concerns, "missing": a.missing, "unmapped": a.unmapped, "warnings": a.warnings,
           "ai_status": a.ai_status, "readings": a.readings or {},
           "assessed_on": a.created_at.isoformat(timespec="minutes")}
    if full:
        out |= {"doctor_id": a.doctor_id, "ai_output": a.ai_output, "dropped": a.dropped, "model": a.model}
    return out
