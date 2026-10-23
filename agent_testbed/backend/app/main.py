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

from agent.assess import run_assessment
from agent.main import AgentUnavailable, close_memory, open_memory, run_turn, thread_id
from app import clinic
from app.config import settings
from app.db import fetch_one, pool
from store import assessments as assessment_store
from store import cases as case_store
from store import messages as message_store
from store import plans as plan_store
from store.db import session
from store.models import Case, PlanProposal
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
    """Run the assessment: the patient's conditions and whether a doctor must
    write the plan. Phase 5 turns it into a draft; phase 6 puts it behind the
    doctor's "Generate plan" button."""
    try:
        return run_assessment(patient_id, body.doctor_id)
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
    """The patient's approved plan, the draft waiting for a doctor, and any open case."""
    with session() as db:
        return {"plan": plan_store.plan_dict(plan_store.latest_plan(db, patient_id)),
                "pending": plan_store.proposal_dict(plan_store.pending_proposal(db, patient_id), full=True),
                "open_case": case_store.case_dict(case_store.open_case(db, patient_id))}


class ReviewIn(BaseModel):
    doctor_id: str
    instructions: str | None = Field(default=None, max_length=4000)
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
        plan = plan_store.approve(db, p, body.doctor_id, instructions, None, body.note)
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


#@app.get("/patients/{id}/plan")
#def patient_pan()