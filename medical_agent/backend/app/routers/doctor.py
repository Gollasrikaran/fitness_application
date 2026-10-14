"""Doctor-facing routes: the case queue, a case's full picture, and plans."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case as sql_case
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import context as ctx
from app.auth import require_doctor
from app.db import get_db
from app.models import Case, ChatMessage, DoctorPlan, Exercise, User
from app.schemas import PlanIn

router = APIRouter(prefix="/doctor", tags=["doctor"])

_URGENCY_ORDER = sql_case({"emergency": 0, "priority": 1, "routine": 2}, value=Case.urgency, else_=3)


def _case_row(c: Case) -> dict:
    return {"id": c.id, "patient": c.user.name, "status": c.status, "urgency": c.urgency, "reason": c.reason,
            "triggers": c.triggers, "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat()}


def _get_case(db: Session, case_id: str) -> Case:
    c = db.get(Case, case_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return c


@router.get("/cases")
def list_cases(status_filter: str = Query("open", alias="status", pattern="^(open|plan_given|closed|all)$"),
               _: User = Depends(require_doctor), db: Session = Depends(get_db)):
    q = select(Case)
    if status_filter != "all":
        q = q.where(Case.status == status_filter)
    rows = db.scalars(q.order_by(_URGENCY_ORDER, Case.created_at)).all()
    return [_case_row(c) for c in rows]


@router.get("/cases/{case_id}")
def get_case(case_id: str, _: User = Depends(require_doctor), db: Session = Depends(get_db)):
    c = _get_case(db, case_id)
    messages = ctx.recent_messages(db, c.user_id, 60)
    return {
        **_case_row(c),
        "summary": c.summary,
        "patient_context": ctx.build_context(db, c.user),
        "transcript": [{"role": m.role, "content": m.content, "decision": m.decision,
                        "created_at": m.created_at.isoformat()} for m in messages],
        "plans": [{"id": p.id, "doctor": p.doctor.name, "instructions": p.instructions,
                   "exercises": p.exercises, "given_on": p.created_at.isoformat()} for p in c.plans],
    }


@router.post("/cases/{case_id}/plan", status_code=201)
def give_plan(case_id: str, body: PlanIn, doctor: User = Depends(require_doctor), db: Session = Depends(get_db)):
    c = _get_case(db, case_id)
    if c.status == "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Case is closed")
    names = {e.activity_type: e for e in db.scalars(select(Exercise))}
    unknown = [e.activity_type for e in body.exercises if e.activity_type not in names]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown exercises: {unknown}")
    exercises = [{**e.model_dump(), "name": names[e.activity_type].display_name,
                  "unit": names[e.activity_type].amount_unit} for e in body.exercises]
    plan = DoctorPlan(case_id=c.id, user_id=c.user_id, doctor_id=doctor.id,
                      instructions=body.instructions.strip(), exercises=exercises)
    db.add(plan)
    c.status = "plan_given"
    # The plan also lands in the patient's chat, so they see it and the agent
    # has it in its history from now on.
    lines = [f"Plan from Dr. {doctor.name}:", body.instructions.strip()]
    lines += [f"- {e['name']}: {e['sets']} x {e['amount']:g} {e['unit']}" + (f" ({e['notes']})" if e["notes"] else "")
              for e in exercises]
    db.add(ChatMessage(user_id=c.user_id, role="doctor", content="\n".join(lines), case_id=c.id))
    db.flush()
    return {"id": plan.id, "case_status": c.status}


@router.post("/cases/{case_id}/close")
def close_case(case_id: str, _: User = Depends(require_doctor), db: Session = Depends(get_db)):
    c = _get_case(db, case_id)
    c.status = "closed"
    return {"id": c.id, "status": c.status}
