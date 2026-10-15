"""Everything the agent knows about a patient, rebuilt fresh on every turn:
profile, conditions, the exercises the safety grid allows them, this week's
progress against last week's, remembered facts, and any doctor case or plan.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (Case, ChatMessage, Condition, DoctorPlan, Exercise, MemoryNote, PlanProposal,
                        ProgressLog, SafetyRule, User)

# Progress signals that send a case to a doctor without asking the LLM.
PAIN_HIGH = 8          # any session this week at or above this
PAIN_RISE = 2.0        # average pain up by at least this much versus last week
MEMORY_NOTES_IN_CONTEXT = 30


def condition_codes(user: User) -> list[str]:
    return [uc.condition_code for uc in user.conditions] or ["none"]


def approved_exercises(db: Session, codes: list[str]) -> list[dict]:
    """Exercises allowed for *every* one of the patient's conditions.

    Fails closed: a "refer" condition allows nothing, and an exercise with no
    rule for one of the conditions is treated as not approved. "avoid" for any
    condition excludes it; "modify" for any condition carries the note along.
    """
    conditions = db.scalars(select(Condition).where(Condition.code.in_(codes))).all()
    if not conditions or any(c.bucket == "refer" for c in conditions):
        return []
    rules: dict[str, dict[str, SafetyRule]] = defaultdict(dict)
    for rule in db.scalars(select(SafetyRule).where(SafetyRule.condition_code.in_(codes))):
        rules[rule.activity_type][rule.condition_code] = rule

    approved = []
    for ex in db.scalars(select(Exercise).order_by(Exercise.display_name)):
        by_condition = rules.get(ex.activity_type, {})
        if set(by_condition) != set(codes):
            continue
        if any(r.verdict == "avoid" for r in by_condition.values()):
            continue
        notes = [r.note for r in by_condition.values() if r.verdict == "modify" and r.note]
        approved.append({
            "activity_type": ex.activity_type, "display_name": ex.display_name,
            "unit": ex.amount_unit, "default_sets": ex.default_sets,
            "default_amount": ex.default_amount,
            "verdict": "modify" if notes else "safe", "notes": notes,
        })
    return approved


def _window_summary(logs: list[ProgressLog], names: dict[str, tuple[str, str]]) -> dict:
    per_exercise: dict[str, dict] = {}
    for log in logs:
        name, unit = names.get(log.activity_type, (log.activity_type, ""))
        row = per_exercise.setdefault(name, {"sessions": 0, "total": 0.0, "unit": unit})
        row["sessions"] += 1
        row["total"] = round(row["total"] + log.sets * log.amount, 1)
    pains = [log.pain_level for log in logs if log.pain_level is not None]
    return {
        "active_days": len({log.logged_on for log in logs}),
        "exercises": per_exercise,
        "pain_avg": round(sum(pains) / len(pains), 1) if pains else None,
        "pain_max": max(pains) if pains else None,
        "pain_readings": len(pains),
    }


def weekly_progress(db: Session, user_id: str, today: date | None = None) -> dict:
    """This week (last 7 days, including today) against the 7 days before."""
    today = today or date.today()
    start_this, start_last = today - timedelta(days=6), today - timedelta(days=13)
    logs = db.scalars(select(ProgressLog).where(
        ProgressLog.user_id == user_id, ProgressLog.logged_on >= start_last,
        ProgressLog.logged_on <= today)).all()
    names = {e.activity_type: (e.display_name, e.amount_unit) for e in db.scalars(select(Exercise))}
    this_week = _window_summary([l for l in logs if l.logged_on >= start_this], names)
    last_week = _window_summary([l for l in logs if l.logged_on < start_this], names)

    signals: list[dict] = []
    if this_week["pain_max"] is not None and this_week["pain_max"] >= PAIN_HIGH:
        signals.append({"code": "pain_high", "escalate": True,
                        "text": f"Pain reached {this_week['pain_max']}/10 after a session this week"})
    if (this_week["pain_avg"] is not None and last_week["pain_avg"] is not None
            and this_week["pain_readings"] >= 2 and last_week["pain_readings"] >= 2
            and this_week["pain_avg"] - last_week["pain_avg"] >= PAIN_RISE):
        signals.append({"code": "pain_rising", "escalate": True,
                        "text": f"Average pain rose from {last_week['pain_avg']} to {this_week['pain_avg']}/10"})
    if this_week["active_days"] == 0 and last_week["active_days"] > 0:
        signals.append({"code": "stopped_exercising", "escalate": False,
                        "text": "No sessions logged this week after being active last week"})
    return {"this_week": this_week, "last_week": last_week, "signals": signals}


def latest_plan(db: Session, user_id: str) -> dict | None:
    plan = db.scalars(select(DoctorPlan).where(DoctorPlan.user_id == user_id)
                      .order_by(DoctorPlan.created_at.desc()).limit(1)).first()
    if plan is None:
        return None
    return {"id": plan.id, "instructions": plan.instructions, "exercises": plan.exercises,
            "doctor": plan.doctor.name, "given_on": plan.created_at.date().isoformat()}


def pending_plan(db: Session, user_id: str) -> dict | None:
    """A drafted plan still waiting for the doctor (not yet the patient's to follow)."""
    p = db.scalars(select(PlanProposal).where(PlanProposal.user_id == user_id, PlanProposal.status == "pending")
                   .order_by(PlanProposal.created_at.desc()).limit(1)).first()
    if p is None:
        return None
    return {"id": p.id, "kind": p.kind, "requested_on": p.created_at.date().isoformat()}


def open_case(db: Session, user_id: str) -> Case | None:
    return db.scalars(select(Case).where(Case.user_id == user_id, Case.status == "open")
                      .order_by(Case.created_at.desc()).limit(1)).first()


def case_dict(case: Case | None) -> dict | None:
    if case is None:
        return None
    return {"id": case.id, "status": case.status, "urgency": case.urgency, "reason": case.reason,
            "opened_on": case.created_at.date().isoformat()}


def build_context(db: Session, user: User, today: date | None = None) -> dict:
    profile = user.profile
    codes = condition_codes(user)
    conditions = db.scalars(select(Condition).where(Condition.code.in_(codes))).all()
    bmi = None
    if profile and profile.height_cm and profile.weight_kg:
        bmi = round(profile.weight_kg / (profile.height_cm / 100) ** 2, 1)
    notes = db.scalars(select(MemoryNote).where(MemoryNote.user_id == user.id)
                       .order_by(MemoryNote.created_at.desc()).limit(MEMORY_NOTES_IN_CONTEXT)).all()
    return {
        "patient": {
            "name": user.name,
            "age": profile.age if profile else None,
            "sex": profile.sex if profile else None,
            "height_cm": profile.height_cm if profile else None,
            "weight_kg": profile.weight_kg if profile else None,
            "bmi": bmi,
            "experience": profile.experience if profile else None,
        },
        "conditions": [{"code": c.code, "name": c.display_name, "bucket": c.bucket} for c in conditions],
        "approved_exercises": approved_exercises(db, codes),
        "progress": weekly_progress(db, user.id, today),
        "memory": [n.note for n in reversed(notes)],
        "open_case": case_dict(open_case(db, user.id)),
        "doctor_plan": latest_plan(db, user.id),
        "pending_plan": pending_plan(db, user.id),
    }


def recent_messages(db: Session, user_id: str, limit: int) -> list[ChatMessage]:
    rows = db.scalars(select(ChatMessage).where(ChatMessage.user_id == user_id)
                      .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit)).all()
    return list(reversed(rows))
