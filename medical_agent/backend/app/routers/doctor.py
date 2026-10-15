"""Doctor-facing routes: the case queue, a case's full picture, plans, and
reviewing the plans drafted by the rules."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case as sql_case
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import context as ctx
from app.agent import plans
from app.auth import require_doctor
from app.db import get_db
from app.models import Case, DoctorPlan, Exercise, PlanProposal, User
from app.schemas import ApproveIn, PlanExercise, PlanIn, RejectIn

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


def _plan_exercises(db: Session, items: list[PlanExercise]) -> list[dict]:
    names = {e.activity_type: e for e in db.scalars(select(Exercise))}
    unknown = [e.activity_type for e in items if e.activity_type not in names]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown exercises: {unknown}")
    return [{**e.model_dump(), "name": names[e.activity_type].display_name,
             "unit": names[e.activity_type].amount_unit} for e in items]


@router.post("/cases/{case_id}/plan", status_code=201)
def give_plan(case_id: str, body: PlanIn, doctor: User = Depends(require_doctor), db: Session = Depends(get_db)):
    c = _get_case(db, case_id)
    if c.status == "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Case is closed")
    exercises = _plan_exercises(db, body.exercises)
    # The doctor's own plan replaces any draft still waiting for review.
    plans.supersede_pending(db, c.user_id)
    plan = plans.give_plan(db, doctor, c.user_id, body.instructions.strip(), exercises, case_id=c.id)
    c.status = "plan_given"
    return {"id": plan.id, "case_status": c.status}


@router.post("/cases/{case_id}/close")
def close_case(case_id: str, _: User = Depends(require_doctor), db: Session = Depends(get_db)):
    c = _get_case(db, case_id)
    c.status = "closed"
    return {"id": c.id, "status": c.status}


# ── Plans drafted by the rules, waiting for a doctor ────────────────────────

def _proposal_row(p: PlanProposal) -> dict:
    return {**plans.proposal_dict(p), "patient": p.user.name, "reason": p.reason}


def _get_proposal(db: Session, proposal_id: str) -> PlanProposal:
    p = db.get(PlanProposal, proposal_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return p


def _pending(p: PlanProposal) -> None:
    if p.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Proposal is already {p.status}")


@router.get("/proposals")
def list_proposals(status_filter: str = Query("pending", alias="status",
                                              pattern="^(pending|approved|rejected|superseded|all)$"),
                   _: User = Depends(require_doctor), db: Session = Depends(get_db)):
    q = select(PlanProposal)
    if status_filter != "all":
        q = q.where(PlanProposal.status == status_filter)
    return [_proposal_row(p) for p in db.scalars(q.order_by(PlanProposal.created_at)).all()]


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, _: User = Depends(require_doctor), db: Session = Depends(get_db)):
    p = _get_proposal(db, proposal_id)
    def plan_out(plan_id: str | None) -> dict | None:
        plan = db.get(DoctorPlan, plan_id) if plan_id else None
        return {"id": plan.id, "doctor": plan.doctor.name, "instructions": plan.instructions,
                "exercises": plan.exercises} if plan else None

    return {
        **_proposal_row(p),
        "instructions": p.instructions, "exercises": p.exercises, "changes": p.changes,
        "patient_note": p.patient_note, "review_note": p.review_note,
        "based_on_plan": plan_out(p.based_on_plan_id),
        "approved_plan": plan_out(p.approved_plan_id),  # as sent, with the doctor's edits
        "patient_context": ctx.build_context(db, p.user),
    }


@router.post("/proposals/{proposal_id}/approve", status_code=201)
def approve_proposal(proposal_id: str, body: ApproveIn, doctor: User = Depends(require_doctor),
                     db: Session = Depends(get_db)):
    p = _get_proposal(db, proposal_id)
    _pending(p)
    instructions = body.instructions.strip() if body.instructions else p.instructions
    if not instructions:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "This draft has no plan in it: write the instructions")
    exercises = p.exercises if body.exercises is None else _plan_exercises(db, body.exercises)
    plan = plans.approve(db, p, doctor, instructions, exercises, body.note)
    return {"id": plan.id, "proposal_status": p.status}


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, body: RejectIn, doctor: User = Depends(require_doctor),
                    db: Session = Depends(get_db)):
    p = _get_proposal(db, proposal_id)
    _pending(p)
    plans.reject(p, doctor, body.note.strip())
    return {"id": p.id, "status": p.status}
