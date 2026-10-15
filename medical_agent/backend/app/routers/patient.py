"""Patient-facing routes: profile, progress logging, chat, and plans."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agent import context as ctx
from app.agent import plans
from app.agent.triage import AgentUnavailable, handle_message
from app.auth import require_patient
from app.db import get_db
from app.models import (ChatMessage, Condition, DoctorPlan, Exercise, Profile, ProgressLog, User,
                        UserCondition)
from app.schemas import ChatIn, PlanFeedbackIn, ProfileIn, ProgressIn

router = APIRouter(tags=["patient"])


@router.get("/conditions")
def list_conditions(db: Session = Depends(get_db)):
    rows = db.scalars(select(Condition).order_by(Condition.display_order)).all()
    return [{"code": c.code, "name": c.display_name, "bucket": c.bucket} for c in rows]


@router.get("/exercises")
def list_exercises(db: Session = Depends(get_db)):
    rows = db.scalars(select(Exercise).order_by(Exercise.display_name)).all()
    return [{"activity_type": e.activity_type, "name": e.display_name, "unit": e.amount_unit,
             "default_sets": e.default_sets, "default_amount": e.default_amount} for e in rows]


def _profile_out(user: User) -> dict | None:
    p = user.profile
    if p is None:
        return None
    return {"age": p.age, "sex": p.sex, "height_cm": p.height_cm, "weight_kg": p.weight_kg,
            "experience": p.experience, "conditions": [uc.condition_code for uc in user.conditions]}


@router.get("/profile")
def get_profile(user: User = Depends(require_patient)):
    return _profile_out(user)


@router.put("/profile")
def put_profile(body: ProfileIn, user: User = Depends(require_patient), db: Session = Depends(get_db)):
    codes = sorted(set(body.conditions) - {"none"})
    known = set(db.scalars(select(Condition.code).where(Condition.code.in_(codes))))
    unknown = set(codes) - known
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown condition codes: {sorted(unknown)}")
    fields = body.model_dump(exclude={"conditions"})
    old_codes = ctx.condition_codes(user)
    if user.profile is None:
        db.add(Profile(user_id=user.id, **fields))
    else:
        for k, v in fields.items():
            setattr(user.profile, k, v)
    db.execute(delete(UserCondition).where(UserCondition.user_id == user.id))
    db.add_all(UserCondition(user_id=user.id, condition_code=c) for c in codes)
    db.flush()
    db.refresh(user)
    plans.on_profile_saved(db, user, old_codes)
    return _profile_out(user)


@router.post("/progress", status_code=201)
def log_progress(body: ProgressIn, user: User = Depends(require_patient), db: Session = Depends(get_db)):
    if db.get(Exercise, body.activity_type) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown exercise")
    logged_on = body.logged_on or date.today()
    if logged_on > date.today() or logged_on < date.today() - timedelta(days=30):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Date must be within the last 30 days")
    entry = ProgressLog(user_id=user.id, activity_type=body.activity_type, sets=body.sets,
                        amount=body.amount, pain_level=body.pain_level, logged_on=logged_on)
    db.add(entry)
    db.flush()
    return {"id": entry.id}


@router.get("/progress")
def list_progress(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    since = date.today() - timedelta(days=13)
    rows = db.scalars(select(ProgressLog).where(ProgressLog.user_id == user.id, ProgressLog.logged_on >= since)
                      .order_by(ProgressLog.logged_on.desc(), ProgressLog.id.desc())).all()
    names = {e.activity_type: (e.display_name, e.amount_unit) for e in db.scalars(select(Exercise))}
    return [{"id": r.id, "activity_type": r.activity_type, "name": names[r.activity_type][0],
             "unit": names[r.activity_type][1], "sets": r.sets, "amount": r.amount,
             "pain_level": r.pain_level, "logged_on": r.logged_on.isoformat()} for r in rows]


@router.get("/agent/context")
def agent_context(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    """Exactly what the agent sees about this patient (shown in the UI sidebar)."""
    return ctx.build_context(db, user)


def _message_out(m: ChatMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "decision": m.decision,
            "exercises": m.exercises or [], "case_id": m.case_id, "created_at": m.created_at.isoformat()}


@router.get("/chat")
def chat_history(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    return [_message_out(m) for m in ctx.recent_messages(db, user.id, 200)]


@router.post("/chat")
def chat(body: ChatIn, user: User = Depends(require_patient), db: Session = Depends(get_db)):
    if user.profile is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Please complete your profile first")
    try:
        result = handle_message(db, user, body.message.strip())
    except AgentUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return {"reply": result.reply, "decision": result.decision, "reason": result.reason,
            "exercises": result.exercises, "case": result.case, "flags": result.flags}


@router.get("/plans")
def my_plans(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    rows = db.scalars(select(DoctorPlan).where(DoctorPlan.user_id == user.id)
                      .order_by(DoctorPlan.created_at.desc())).all()
    return [{"id": p.id, "case_id": p.case_id, "doctor": p.doctor.name, "instructions": p.instructions,
             "exercises": p.exercises, "given_on": p.created_at.isoformat()} for p in rows]


@router.get("/plans/pending")
def my_pending_plan(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    """A plan waiting for the doctor. Status only: the patient sees the
    exercises once the doctor has approved them."""
    p = plans.pending_proposal(db, user.id)
    return plans.proposal_dict(p) if p else None


@router.post("/plans/too-hard", status_code=201)
def plan_too_hard(body: PlanFeedbackIn, user: User = Depends(require_patient), db: Session = Depends(get_db)):
    plan = plans.latest_plan(db, user.id)
    if plan is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You don't have a plan yet")
    if plans.pending_proposal(db, user.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A new plan is already waiting for your doctor")
    unknown = set(body.activity_types) - {e["activity_type"] for e in plan.exercises}
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Not in your plan: {sorted(unknown)}")
    note = body.note.strip() if body.note else None
    if body.pain_level is not None and body.pain_level >= plans.PAIN_TO_DOCTOR:
        case = plans.escalate_painful_plan(db, user, plan, body.activity_types, body.pain_level, note)
        return {"status": "doctor_case", "case": ctx.case_dict(case), "proposal": None}
    proposal = plans.request_easier(db, user, plan, body.activity_types, note)
    return {"status": "pending_review", "case": None, "proposal": plans.proposal_dict(proposal)}
