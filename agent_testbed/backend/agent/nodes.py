"""One function per graph node. Each returns only the state fields it changes."""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.conditions import Reference, RuleResult, load_reference, rule_findings
from agent.llm import ask
from agent.prompts import DOCTOR_CHAT, record_block
from agent.routing import finalize
from app.source import clinic
from store import assessments as assessment_store
from store import cases as case_store
from store import plans as plan_store
from store.db import session
from store.models import Exercise

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
    today = date.today()
    with session() as db:
        ref = load_reference(db)
        context["assessment"] = assessment_store.assessment_dict(assessment_store.latest(db, pid))
        context["doctor_plan"] = plan_store.plan_dict(plan_store.latest_plan(db, pid))
        context["pending_plan"] = plan_store.proposal_dict(plan_store.pending_proposal(db, pid))
        context["open_case"] = case_store.case_dict(case_store.open_case(db, pid))
        codes, context["chat_conditions"], context["chat_exercises"] = programme(
            db, context, ref, rule_findings(context, ref, today), context["assessment"], today)
    return {"context": context, "conditions": codes}


# The exercise types as the chat shows them, in this order.
_TYPE_NAMES = {"aerobic": "Walking-type", "strength": "Strength", "balance": "Balance", "breathing": "Breathing",
               "mobility": "Mobility", "stretch": "Stretch", "isometric": "Holding (isometric)"}


def programme(db: Session, context: dict, ref: Reference, rules: RuleResult, assessment: dict | None,
              today: date) -> tuple[list[str], str, str]:
    """What the chat knows about the patient's exercise safety (no AI):
    (condition codes, CONDITIONS text, EXERCISES text). The conditions as
    decided (e.g. "BP under control", not the raw bp_any) by the latest
    assessment, else by the rules alone; and the exercises of our programme
    the safety rules allow for them, as a draft would get them."""
    if assessment:
        decided, readings = assessment, assessment.get("readings") or {}
        source = f"the latest assessment ({assessment['assessed_on'][:10]}, rules and AI)"
    else:  # no plan generated yet: the rules alone, as Generate plan's first step
        decided = finalize(context, ref, rules, None, [], today)
        # Only about the missing AI step, which the chat doesn't run.
        decided["severe_reasons"] = [r for r in decided["severe_reasons"] if not r.startswith("Assessment incomplete")]
        vitals = context.get("vitals_recent") or [{**v.get("vitals", {}), "date": v["date"]}
                                                  for v in context["visits"]]
        windows = {m: ref.windows.get((m, "reading")) or d for m, d in plan_store.READING_WINDOWS.items()}
        readings = plan_store.latest_readings(vitals, today, plan_store.READING_DAYS, windows)
        source = "our rules alone (no plan generated yet)"
    codes, reasons = decided["codes"], decided["severe_reasons"]

    lines = [f"Decided by {source}:"]
    lines += [f"- {c['name']} ({c['code']}): " + "; ".join(c["evidence"][:3]) for c in decided["conditions"]] \
        or ["- none of our conditions found"]
    if reasons:
        lines.append("A doctor must write this patient's plan: " + "; ".join(reasons))
    if decided.get("concerns"):
        lines.append("Concerns: " + "; ".join(decided["concerns"]))

    patient = context.get("patient") or {}
    allowed, left_out = ([], []) if reasons else plan_store.candidates(
        db, codes, patient.get("age"), (context.get("body") or {}).get("bmi"), readings)
    if reasons:
        exercises = ["None: a doctor writes this patient's plan (see CONDITIONS)."]
    elif not allowed:
        exercises = ["None: no exercise in our programme is allowed for these conditions.", *left_out]
    else:
        position = {e.activity_type: e.position for e in db.scalars(select(Exercise))}
        groups = defaultdict(list)
        for e in allowed:
            groups[e["exercise_type"]].append(f"{e['name']} ({position.get(e['activity_type'])})"
                                              + (f" [caution: {e['notes']}]" if e["notes"] else ""))
        exercises = [f"- {name}: " + "; ".join(groups[kind]) for kind, name in _TYPE_NAMES.items() if groups[kind]]
        exercises += [f"Left out by the rules: {line}" for line in left_out]
    return codes, "\n".join(lines), "\n".join(exercises)


# ── chat (AI): a doctor asking about one of their patients ───────

def _history(messages: list) -> list[dict]:
    """The conversation in the API's shape, starting with the doctor's message."""
    turns = [{"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": str(m.content)}
             for m in messages if isinstance(m, (HumanMessage, AIMessage)) and str(m.content).strip()]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return turns


_BOLD = re.compile(r"\*\*|__")
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.M)
_STAR_BULLET = re.compile(r"^([ \t]*)[*•][ \t]+", re.M)


def plain(text: str) -> str:
    """The reply as plain text: the chat window shows Markdown as raw
    characters ("**Correction:**"), and the model sometimes writes it
    despite the prompt."""
    return _STAR_BULLET.sub(r"\1- ", _HEADING.sub("", _BOLD.sub("", text)))


def chat(state: dict) -> dict:
    ctx = state["context"]
    system = (f"{DOCTOR_CHAT}\n\nCONDITIONS\n{ctx.get('chat_conditions') or 'none'}"
              f"\n\nEXERCISES\n{ctx.get('chat_exercises') or 'none'}\n\nPATIENT_RECORD\n{record_block(state)}")
    try:
        reply = ask(system, _history(state["messages"][-HISTORY_FOR_CHAT:]))
    except Exception as exc:
        log.error("Chat call failed: %s", exc)
        raise AgentUnavailable("The assistant is unavailable right now. Please try again in a minute.")
    return {"messages": [AIMessage(content=plain(reply))]}
