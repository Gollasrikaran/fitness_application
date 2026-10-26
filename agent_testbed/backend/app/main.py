"""Agent testbed API. No login: a doctor picks a patient and asks the agent
about them; a patient only sees the plan a doctor approved.

    uvicorn app.main:app --port 8001 --reload --reload-dir app --reload-dir agent --reload-dir store
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.draft import generate_plan
from agent.main import AgentUnavailable, close_memory, open_memory, run_turn, thread_id
from app import clinic
from app.config import settings
from app.db import fetch_one, pool
from store import assessments as assessment_store
from store import cases as case_store
from store import messages as message_store
from store import plans as plan_store
from store.db import session
from store.models import Assessment, Case, PlanProposal
from store.seed import init_store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    pool.open()
    init_store()  # the agent's own tables in the temporary database
    open_memory()  # the agent's conversation memory, also in the temporary database
    yield
    close_memory()
    pool.close(timeout=1)  # don't let a slow pooler hold up --reload


app = FastAPI(title="Agent testbed", version="0.1.0", lifespan=lifespan)
# Any localhost port is allowed: Vite moves to 5176, 5177... when 5175 is busy.
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+", allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok", "clinic_db": fetch_one("SELECT current_setting('transaction_read_only') AS ro")}


@app.get("/doctors")
def list_doctors():
    return clinic.doctors()


@app.get("/patients")
def list_patients(doctor_id: str | None = None, search: str = "",
                  limit: int = Query(100, ge=1, le=500), min_visits: int = Query(2, ge=1, le=50)):
    return clinic.patients(doctor_id, search, limit, min_visits)


@app.get("/patients/{patient_id}/context")
def patient_context(patient_id: str):
    context = clinic.patient_context(patient_id)
    if context is None:
        raise HTTPException(404, "Patient not found")
    return context


class ChatIn(BaseModel):
    patient_id: str
    doctor_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)


@app.post("/chat")
def chat(body: ChatIn):
    """A doctor asks the agent about one of their patients."""
    try:
        return run_turn(body.patient_id, body.doctor_id, body.message.strip())
    except AgentUnavailable as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:  # unknown patient
        raise HTTPException(404, str(exc))


@app.get("/chat/history")
def chat_history(patient_id: str, doctor_id: str):
    """The saved conversation, oldest first, so a reload shows it again."""
    with session() as db:
        return message_store.history(db, thread_id(patient_id, doctor_id))


# ── The agent's own data: plans, drafts, cases (temporary database) ──────────

class AssessIn(BaseModel):
    doctor_id: str = Field(min_length=1)


@app.post("/patients/{patient_id}/assess")
def assess(patient_id: str, body: AssessIn):
    """The doctor's "Generate plan": assess the patient (conditions, severity),
    then draft a plan for the doctor to review. Severe: a "doctor must write
    the plan" item with no exercises. Returns {assessment, draft}."""
    try:
        return generate_plan(patient_id, body.doctor_id)
    except ValueError as exc:  # unknown patient
        raise HTTPException(404, str(exc))


@app.get("/patients/{patient_id}/assessment")
def latest_assessment(patient_id: str):
    with session() as db:
        return {"assessment": assessment_store.assessment_dict(assessment_store.latest(db, patient_id), full=True)}


@app.get("/patients/{patient_id}/plan")
def approved_plan(patient_id: str):
    """What the patient sees: the latest plan a doctor approved, nothing else."""
    with session() as db:
        return {"plan": plan_store.plan_dict(plan_store.latest_plan(db, patient_id))}


@app.get("/patients/{patient_id}/agent")
def agent_data(patient_id: str):
    """The patient's approved plan, the draft waiting for a doctor (with the
    assessment behind it), and any open case."""
    with session() as db:
        pending = plan_store.pending_proposal(db, patient_id)
        assessment = db.get(Assessment, pending.assessment_id) if pending and pending.assessment_id else None
        return {"plan": plan_store.plan_dict(plan_store.latest_plan(db, patient_id)),
                "pending": plan_store.proposal_dict(pending, full=True),
                "assessment": assessment_store.assessment_dict(assessment),
                "open_case": case_store.case_dict(case_store.open_case(db, patient_id))}


@app.get("/review-queue")
def review_queue(doctor_id: str):
    """Drafts this doctor generated that are waiting for review, oldest first."""
    with session() as db:
        items = plan_store.review_queue(db, doctor_id)
    briefs = clinic.patient_briefs([i["patient_id"] for i in items])
    return [{**i, "age": briefs.get(i["patient_id"], {}).get("age"), "sex": briefs.get(i["patient_id"], {}).get("sex")}
            for i in items]


@app.get("/exercises")
def exercises(conditions: str = ""):
    """All exercises for the doctor's picker, with what the safety grid says
    for these conditions (comma-separated codes)."""
    codes = [c for c in conditions.split(",") if c.strip()]
    with session() as db:
        return plan_store.exercise_catalog(db, codes)


class ExerciseIn(BaseModel):
    activity_type: str
    sets: int = Field(ge=1, le=50)
    amount: float = Field(gt=0, le=1000)
    notes: str = Field(default="", max_length=500)


class CheckIn(BaseModel):
    conditions: list[str]
    exercises: list[ExerciseIn]


@app.post("/plans/check")
def check_plan(body: CheckIn):
    """Small warnings for a doctor's edit, per exercise. They never block."""
    with session() as db:
        return {"warnings": plan_store.doctor_warnings(db, [e.model_dump() for e in body.exercises], body.conditions)}


class ReviewIn(BaseModel):
    doctor_id: str
    instructions: str | None = Field(default=None, max_length=4000)
    exercises: list[ExerciseIn] | None = None  # the doctor's edit; None keeps the draft's
    note: str | None = Field(default=None, max_length=1000)


def _pending(db, proposal_id: str) -> PlanProposal:
    p = db.get(PlanProposal, proposal_id)
    if p is None:
        raise HTTPException(404, "Draft not found")
    if p.status != "pending":
        raise HTTPException(409, f"Draft is already {p.status}")
    return p


@app.post("/proposals/{proposal_id}/approve", status_code=201)
def approve_proposal(proposal_id: str, body: ReviewIn):
    with session() as db:
        p = _pending(db, proposal_id)
        instructions = (body.instructions or "").strip() or p.instructions
        if not instructions:
            raise HTTPException(422, "This draft has no plan in it: write the instructions")
        exercises = None
        if body.exercises is not None:  # the doctor has the final say: only input errors are refused
            try:
                exercises = plan_store.doctor_exercises(db, [e.model_dump() for e in body.exercises])
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        plan = plan_store.approve(db, p, body.doctor_id, instructions, exercises, body.note)
        return {"plan": plan_store.plan_dict(plan)}


@app.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, body: ReviewIn):
    if not (body.note or "").strip():
        raise HTTPException(422, "Give a reason for rejecting")
    with session() as db:
        p = _pending(db, proposal_id)
        plan_store.reject(p, body.doctor_id, body.note.strip())
        return {"status": p.status}


@app.post("/cases/{case_id}/close")
def close_case(case_id: str, body: ReviewIn):
    with session() as db:
        case = db.get(Case, case_id)
        if case is None:
            raise HTTPException(404, "Case not found")
        case_store.close_case(case, body.doctor_id, (body.note or "").strip() or None)
        return {"status": case.status}
