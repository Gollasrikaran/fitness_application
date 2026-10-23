"""One function per graph node. Each returns only the state fields it changes."""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, SystemMessage

from agent.conditions import load_reference, rule_findings
from agent.llm import chat_model
from agent.prompts import DOCTOR_CHAT, record_block
from app import clinic
from store import assessments as assessment_store
from store import cases as case_store
from store import plans as plan_store
from store.db import session

log = logging.getLogger("agent")

HISTORY_FOR_CHAT = 20  # messages the chat model sees


class AgentUnavailable(Exception):
    pass


# ── load_context (no AI) ─────────────────────────────────────────

def load_context(state: dict) -> dict:
    context = clinic.patient_context(state["patient_id"])
    if context is None:
        raise ValueError("Patient not found")
    pid = state["patient_id"]
    with session() as db:
        # The rules' quick read of the record (no AI); the full assessment is
        # run only when the doctor asks for a plan.
        rules = rule_findings(context, load_reference(db))
        context["assessment"] = assessment_store.assessment_dict(assessment_store.latest(db, pid))
        context["doctor_plan"] = plan_store.plan_dict(plan_store.latest_plan(db, pid))
        context["pending_plan"] = plan_store.proposal_dict(plan_store.pending_proposal(db, pid))
        context["open_case"] = case_store.case_dict(case_store.open_case(db, pid))
    context["agent_conditions"] = sorted({f"{f.code}: {f.where}: \"{f.quote}\"" for f in rules.findings})
    context["agent_conditions"] += [f"unmapped {u}" for u in rules.unmapped]
    context["agent_conditions"] += [f"warning: {w['label']} on {w['date']}" for w in rules.warnings]
    return {"context": context, "conditions": sorted({f.code for f in rules.findings})}


# ── chat (AI): a doctor asking about one of their patients ───────

def chat(state: dict) -> dict:
    evidence = "\n".join(state["context"].get("agent_conditions", [])) or "none"
    system = [SystemMessage(content=DOCTOR_CHAT),
              SystemMessage(content=f"AGENT_CONDITIONS\n{evidence}\n\nPATIENT_RECORD\n{record_block(state)}")]
    try:
        reply = chat_model().invoke([*system, *state["messages"][-HISTORY_FOR_CHAT:]])
    except Exception as exc:
        log.error("Chat call failed: %s", exc)
        raise AgentUnavailable("The assistant is unavailable right now. Please try again in a minute.")
    return {"messages": [AIMessage(content=str(reply.content).strip())]}
