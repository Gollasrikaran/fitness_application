"""One function per graph node. Each returns only the state fields it changes."""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agent import red_flags
from agent.conditions import map_conditions
from agent.llm import chat_model
from agent.prompts import DOCTOR_CHAT, PATIENT_CHAT, SUPERVISOR, record_block
from agent.routing import PAIN_TO_DOCTOR, condition_floor, decide_route
from app import clinic
from store import cases as case_store
from store import plans as plan_store
from store.db import session

log = logging.getLogger("agent")

HISTORY_FOR_CHAT = 20       # messages the chat model sees
HISTORY_FOR_SUPERVISOR = 6  # messages the supervisor sees


class AgentUnavailable(Exception):
    pass


def _last_user_text(state: dict) -> str:
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage):
            return str(m.content)
    return ""


# ── load_context (no AI) ─────────────────────────────────────────

def load_context(state: dict) -> dict:
    context = clinic.patient_context(state["patient_id"])
    if context is None:
        raise ValueError("Patient not found")
    conditions, evidence = map_conditions(context)
    context["agent_conditions"] = evidence
    pid = state["patient_id"]
    with session() as db:
        if state["mode"] == "patient":
            plan_store.sync_conditions(db, pid, conditions, context["patient"]["age"], context["body"]["bmi"])
        context["doctor_plan"] = plan_store.plan_dict(plan_store.latest_plan(db, pid))
        context["pending_plan"] = plan_store.proposal_dict(plan_store.pending_proposal(db, pid))
        context["open_case"] = case_store.case_dict(case_store.open_case(db, pid))
    # Fresh per turn: the checkpointer keeps the last turn's values otherwise.
    return {"context": context, "conditions": conditions, "red_flags": [], "forced_reasons": [],
            "condition_severity": "normal", "request_severity": "normal", "intent": "other",
            "route": "chat", "reason": "", "plan_draft": None, "pain_score": None, "case": None}


# ── safety_screen (no AI) ────────────────────────────────────────

def safety_screen(state: dict) -> dict:
    flags = red_flags.scan(_last_user_text(state))
    floor = condition_floor(state)
    update = {
        "red_flags": [f.code for f in flags],
        "forced_reasons": [f"Red flag: {f.label}" for f in flags if f.level == "priority"],
        "condition_severity": "hard" if floor else "normal",
    }
    emergencies = [f for f in flags if f.level == "emergency"]
    if emergencies:
        update |= {"request_severity": "emergency", "route": "emergency",
                   "reason": "Emergency red flag: " + ", ".join(f.label for f in emergencies)}
    return update


# ── emergency (no AI) ────────────────────────────────────────────

def emergency(state: dict) -> dict:
    text = _last_user_text(state)
    flags = red_flags.scan(text)
    reason = state.get("reason") or "Emergency"
    with session() as db:
        case = case_store.upsert_case(
            db, state["patient_id"], "emergency", reason[:500],
            f'Patient wrote: "{text[:600]}". {reason}. Patient was told to call 112/108 or go to an '
            "emergency department.", [f.code for f in flags] or ["emergency"])
        saved = case_store.case_dict(case)
    return {"messages": [AIMessage(content=red_flags.emergency_reply(flags))], "route": "emergency",
            "case": saved}


# ── supervisor (AI, structured output) ───────────────────────────

class Decision(BaseModel):
    condition_severity: Literal["normal", "hard"]
    request_severity: Literal["normal", "hard", "emergency"]
    intent: Literal["question", "symptom", "plan_request", "plan_too_hard", "other"]
    needs_clarification: bool = False
    pain_score: int | None = Field(default=None, ge=0, le=10)
    reason: str = Field(description="One line for the care team")


def supervisor(state: dict) -> dict:
    floor = condition_floor(state)
    forced = list(state.get("forced_reasons") or [])
    summary = {"conditions": state.get("context", {}).get("agent_conditions", []),
               "rules_say_condition_is_hard_because": floor, "rules_force_doctor_because": forced}
    messages = [SystemMessage(content=SUPERVISOR),
                SystemMessage(content=f"RULES\n{summary}\n\nPATIENT_RECORD\n{record_block(state)}"),
                *state["messages"][-HISTORY_FOR_SUPERVISOR:-1],
                HumanMessage(content=f"LATEST_MESSAGE\n{_last_user_text(state)}")]
    try:
        d: Decision = chat_model(temperature=0).with_structured_output(Decision).invoke(messages)
    except Exception as exc:
        log.error("Supervisor call failed: %s", exc)
        if not forced:
            raise AgentUnavailable("The assistant is unavailable right now. Please try again in a minute.")
        # A hard rule already says doctor: go there without the AI.
        d = Decision(condition_severity="hard" if floor else "normal", request_severity="hard",
                     intent="other", reason="Supervisor unavailable; hard rule applies")

    # The rules can only raise the AI's ratings, never lower them.
    if d.pain_score is not None and d.pain_score >= PAIN_TO_DOCTOR:
        forced.append(f"Patient reported pain {d.pain_score}/10")
    condition = "hard" if floor or d.condition_severity == "hard" else "normal"
    request = d.request_severity
    if forced and request == "normal":
        request = "hard"
    route = decide_route(request_severity=request, forced_reasons=forced, intent=d.intent,
                         needs_clarification=d.needs_clarification)
    reason = "; ".join(filter(None, [d.reason, *forced, *floor]))
    return {"condition_severity": condition, "request_severity": request, "intent": d.intent,
            "pain_score": d.pain_score, "forced_reasons": forced, "route": route, "reason": reason[:600]}


# ── chat (AI): patient mode, clarify, and doctor mode ───────────

def chat(state: dict) -> dict:
    if state["mode"] == "doctor":
        evidence = "\n".join(state["context"].get("agent_conditions", [])) or "none"
        system = [SystemMessage(content=DOCTOR_CHAT),
                  SystemMessage(content=f"AGENT_CONDITIONS\n{evidence}\n\nPATIENT_RECORD\n{record_block(state)}")]
    else:
        system = [SystemMessage(content=PATIENT_CHAT),
                  SystemMessage(content=f"CONDITION_SEVERITY: {state.get('condition_severity')}\n"
                                        f"ROUTE: {state.get('route')}\n\nPATIENT_RECORD\n{record_block(state)}")]
    try:
        reply = chat_model().invoke([*system, *state["messages"][-HISTORY_FOR_CHAT:]])
    except Exception as exc:
        log.error("Chat call failed: %s", exc)
        raise AgentUnavailable("The assistant is unavailable right now. Please try again in a minute.")
    route = state.get("route") if state["mode"] == "patient" else "chat"
    return {"messages": [AIMessage(content=str(reply.content).strip())], "route": route}


# ── doctor_handoff (no AI, for now) ──────────────────────────────

DOCTOR_NOTE = "I've shared this with a doctor on our team, who will review it."


def doctor_handoff(state: dict) -> dict:
    urgency = "priority" if state.get("forced_reasons") or state.get("condition_severity") == "hard" else "routine"
    text = _last_user_text(state)
    triggers = list(state.get("red_flags") or [])
    if state.get("pain_score") is not None and state["pain_score"] >= 7:
        triggers.append("pain_reported_high")
    with session() as db:
        case = case_store.upsert_case(db, state["patient_id"], urgency,
                                      (state.get("reason") or "Agent referred to doctor")[:500],
                                      f'Patient wrote: "{text[:600]}". {state.get("reason", "")}',
                                      triggers or ["agent_referral"])
        saved = case_store.case_dict(case)
    reply = ("Thanks for telling me. To be safe, please rest and avoid anything that makes it worse. "
             + DOCTOR_NOTE)
    return {"messages": [AIMessage(content=reply)], "case": saved}


# ── plan (rule-based engine, no AI; every draft waits for a doctor) ──

def _plan_lines(exercises: list[dict]) -> str:
    return "\n".join(f"- {e['name']}: {e['sets']} x {e['amount']:g} {e['unit']}" for e in exercises)


def plan(state: dict) -> dict:
    ctx, pid, text = state["context"], state["patient_id"], _last_user_text(state)
    age, bmi = ctx["patient"]["age"], ctx["body"]["bmi"]
    draft = None
    with session() as db:
        current = plan_store.latest_plan(db, pid)
        pending = plan_store.pending_proposal(db, pid)
        if state.get("intent") == "plan_too_hard" and current is not None:
            if pending is not None:
                reply = ("A change to your plan is already with your doctor. Until they reply, ease off "
                         "anything that feels too hard, and rest if something hurts.")
            else:
                targets = plan_store.exercises_named(db, text, current.exercises)
                draft = plan_store.request_easier(db, pid, current, targets, text)
                which = ", ".join(c["name"] for c in draft.changes) if targets else "all your exercises"
                reply = (f"Thanks for telling me. I've asked your doctor for an easier version of {which}. "
                         "Until they approve it, do what feels comfortable and stop if anything hurts.")
        else:
            status, draft = plan_store.request_plan(db, pid, state.get("conditions") or ["none"], age, bmi)
            if status == "has_plan":
                reply = (f"Here's the plan your doctor gave you on {current.created_at.date().isoformat()}:\n"
                         f"{_plan_lines(current.exercises)}\nIf any of it feels too hard, tell me which part.")
            elif status == "pending":
                reply = "Your plan is with a doctor on our team for review. You'll see it here once they approve it."
            elif draft.source == "doctor":
                reply = ("Because of your health conditions, a doctor on our team will write your exercise plan "
                         "themselves. I've asked them to. You'll see it here once it's ready.")
            else:
                reply = ("I've drafted a starter exercise plan from your health record and sent it to a doctor "
                         "on our team. You'll see it here once they approve it. Until then, please don't start "
                         "anything new.")
        draft_out = plan_store.proposal_dict(draft, full=True)
    return {"messages": [AIMessage(content=reply)], "plan_draft": draft_out}
