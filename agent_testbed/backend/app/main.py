"""Agent testbed API. No login: pick a patient or a doctor and chat with the agent.

    uvicorn app.main:app --port 8001 --reload --reload-dir app --reload-dir agent --reload-dir store
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.main import AgentUnavailable, run_turn
from app import clinic
from app.config import settings
from app.db import fetch_one, pool
from store import cases as case_store
from store import plans as plan_store
from store.db import session
from store.models import Case, PlanProposal
from store.seed import init_store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    pool.open()
    init_store()  # the agent's own tables in the temporary database
    yield
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
    mode: Literal["patient", "doctor"]
    patient_id: str
    doctor_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


@app.post("/chat")
def chat(body: ChatIn):
    if body.mode == "doctor" and not body.doctor_id:
        raise HTTPException(422, "Pick a doctor first")
    try:
        return run_turn(body.mode, body.patient_id, body.doctor_id, body.message.strip())
    except AgentUnavailable as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:  # unknown patient
        raise HTTPException(404, str(exc))


# ── The agent's own data: plans, drafts, cases (temporary database) ──────────

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
