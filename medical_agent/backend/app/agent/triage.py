"""One chat turn: decide whether to help (self-care), ask, or forward to a doctor.

Order of authority, highest first:
  1. Red flags (red_flags.py)  — emergency: fixed reply, urgent case, no LLM.
  2. Hard rules                — a "refer" condition, a priority red flag, or a
                                 worrying progress signal forces "doctor".
  3. The LLM                   — decides within those limits. It may escalate,
                                 never de-escalate.
  4. Output checks             — a stated pain >= 7 forces "doctor"; a reply
                                 naming an exercise outside the doctor's plan is
                                 replaced. The chat never suggests exercises:
                                 plans only come from a doctor (app.agent.plans).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agent import context as ctx
from app.agent import red_flags
from app.agent.cases import upsert_case
from app.agent.llm import LLMError, complete_json
from app.agent.prompts import build_messages
from app.config import settings
from app.models import Case, ChatMessage, Exercise, MemoryNote, User

log = logging.getLogger("medical_agent.triage")

DECISIONS = ("self_care", "clarify", "doctor", "emergency")
PAIN_SCORE_TO_DOCTOR = 7
DOCTOR_NOTE = "I've shared this with a doctor on our team, who will review it and send you a plan."


class AgentUnavailable(Exception):
    pass


@dataclass
class TurnResult:
    reply: str
    decision: str
    reason: str
    exercises: list[dict] = field(default_factory=list)
    case: dict | None = None
    flags: list[str] = field(default_factory=list)


def _forced_doctor_reasons(context: dict, flags: list[red_flags.Flag]) -> list[str]:
    reasons = [f"Red flag: {f.label}" for f in flags if f.level == "priority"]
    refer = [c["name"] for c in context["conditions"] if c["bucket"] == "refer"]
    if refer:
        reasons.append("Condition needs a doctor: " + ", ".join(refer))
    reasons += [s["text"] for s in context["progress"]["signals"] if s["escalate"]]
    return reasons


def _mentions_unapproved_exercise(reply: str, db: Session, approved: set[str]) -> bool:
    """True if the reply names a catalogue exercise that isn't in the patient's plan."""
    text = reply.lower()
    return any(e.display_name.lower() in text
               for e in db.query(Exercise).all() if e.activity_type not in approved)


def _safe_reply(decision: str) -> str:
    """Used when the model's reply named an exercise it shouldn't have. Cutting
    the offending sentence leaves broken fragments, so the whole reply goes."""
    if decision == "doctor":
        return ("To be safe, please hold off on any new or strenuous exercise for now, and rest if "
                "something hurts. " + DOCTOR_NOTE)
    return ("Please stick to the exercises in the plan your doctor gave you, and stop if anything hurts "
            "more. If you'd like a change, your doctor can review your plan.")


def _save_turn(db: Session, user: User, message: str, result: TurnResult, case: Case | None) -> None:
    db.add(ChatMessage(user_id=user.id, role="user", content=message, case_id=case.id if case else None))
    db.flush()  # keeps created_at ordering: the user's message first
    db.add(ChatMessage(user_id=user.id, role="assistant", content=result.reply, decision=result.decision,
                       exercises=result.exercises or None, case_id=case.id if case else None))


def _remember(db: Session, user: User, facts: object, known: list[str]) -> None:
    if not isinstance(facts, list):
        return
    seen = {k.strip().lower() for k in known}
    for fact in facts[:3]:
        if isinstance(fact, str) and fact.strip() and fact.strip().lower() not in seen:
            db.add(MemoryNote(user_id=user.id, note=fact.strip()[:300]))
            seen.add(fact.strip().lower())


def handle_message(db: Session, user: User, message: str,
                   llm: Callable[[list[dict]], dict] | None = None) -> TurnResult:
    llm = llm or complete_json
    context = ctx.build_context(db, user)
    flags = red_flags.scan(message)
    flag_codes = [f.code for f in flags]

    # 1. Emergency: never wait on the LLM.
    emergencies = [f for f in flags if f.level == "emergency"]
    if emergencies:
        labels = ", ".join(f.label for f in emergencies)
        case = upsert_case(db, user, "emergency", f"Emergency red flag: {labels}",
                           f'Patient wrote: "{message[:600]}". Automatic red-flag match: {labels}. '
                           "Patient was told to call 112/108 or go to an emergency department.",
                           flag_codes)
        result = TurnResult(red_flags.emergency_reply(flags), "emergency", f"Red flag: {labels}",
                            case=ctx.case_dict(case), flags=flag_codes)
        _save_turn(db, user, message, result, case)
        return result

    # 2. Hard rules that force a doctor.
    forced = _forced_doctor_reasons(context, flags)
    history = [(m.role, m.content) for m in ctx.recent_messages(db, user.id, settings.chat_history_turns)]
    messages = build_messages(context, history, message, "doctor" if forced else None, forced)

    # 3. The LLM.
    try:
        out = llm(messages)
    except LLMError as exc:
        log.error("LLM call failed: %s", exc)
        if not forced:
            raise AgentUnavailable("The assistant is unavailable right now. Please try again in a minute.")
        out = {"decision": "doctor", "reply": "", "reason": "; ".join(forced), "urgency": "priority",
               "doctor_summary": None, "new_facts": []}

    decision = out.get("decision") if out.get("decision") in ("self_care", "clarify", "doctor") else "doctor"
    reply = str(out.get("reply") or "").strip()
    reason = str(out.get("reason") or "").strip()[:500]
    triggers = list(flag_codes) + [s["code"] for s in context["progress"]["signals"] if s["escalate"]]

    # 4. Output checks.
    pain = out.get("pain_score")
    if isinstance(pain, (int, float)) and pain >= PAIN_SCORE_TO_DOCTOR:
        forced.append(f"Patient reported pain {int(pain)}/10")
        triggers.append("pain_reported_high")
    if forced and decision != "doctor":
        decision = "doctor"
        reply = (reply + " " if reply else "") + DOCTOR_NOTE
    if decision == "doctor" and not reply:
        reply = ("Thanks for telling me. To be safe, please rest and avoid any movement that makes it worse. "
                 + DOCTOR_NOTE)

    plan = context["doctor_plan"]
    in_plan = {e["activity_type"] for e in plan["exercises"]} if plan else set()
    if _mentions_unapproved_exercise(reply, db, in_plan):
        reply = _safe_reply(decision)

    case = None
    if decision == "doctor":
        urgency = "priority" if (out.get("urgency") == "priority" or forced) else "routine"
        all_reasons = forced + ([reason] if reason else [])
        summary = str(out.get("doctor_summary") or "").strip() or (
            f'Patient wrote: "{message[:600]}". Escalated because: {"; ".join(all_reasons) or "assistant judgement"}.')
        case = upsert_case(db, user, urgency, "; ".join(all_reasons)[:500] or "Assistant referred to doctor",
                           summary, triggers)

    _remember(db, user, out.get("new_facts"), context["memory"])
    result = TurnResult(reply, decision, reason or "; ".join(forced), [],
                        ctx.case_dict(case) if case else context["open_case"], flag_codes)
    _save_turn(db, user, message, result, case)
    return result
