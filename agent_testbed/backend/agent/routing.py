"""Routing rules. Plain code: the AI's ratings go in, but these rules decide.

The grid (plan.md section 4):
                    normal request          hard request
  normal condition  chat                    doctor
  hard condition    chat, restricted        doctor
Emergencies skip everything. The rules can only escalate the AI's choice.
"""
from __future__ import annotations

from agent.conditions import REFER

PAIN_TO_DOCTOR = 7


def condition_floor(state: dict) -> list[str]:
    """Reasons the patient's condition is "hard" whatever the AI says."""
    ctx = state["context"]
    reasons = [f"Condition needs a doctor: {c}" for c in state.get("conditions", []) if c in REFER]
    reasons += [f"Critical vital: {f['code']} = {f['value']} on {f['date']}"
                for f in ctx["vital_flags"] if f["severity"] == "CRITICAL"]
    reasons += [f"Emergency visit on {e['date']}" for e in ctx["alerts"]["emergencies"]]
    return reasons


def decide_route(*, request_severity: str, forced_reasons: list[str], intent: str,
                 needs_clarification: bool) -> str:
    if request_severity == "emergency":
        return "emergency"
    # "Too hard" is a dose question for the plan rules, unless a hard rule
    # applies (pain >= 7, a red flag): then it's a doctor's question.
    if intent == "plan_too_hard" and not forced_reasons:
        return "plan"
    if forced_reasons or request_severity == "hard":
        return "doctor"
    if intent in ("plan_request", "plan_too_hard"):
        return "plan"
    if needs_clarification:
        return "clarify"
    return "chat"


# ── Conditional edges ────────────────────────────────────────────

def after_load(state: dict) -> str:
    return "chat" if state["mode"] == "doctor" else "safety_screen"


def after_safety(state: dict) -> str:
    return "emergency" if state.get("request_severity") == "emergency" else "supervisor"


def after_supervisor(state: dict) -> str:
    return {"chat": "chat", "clarify": "chat", "plan": "plan",
            "doctor": "doctor_handoff", "emergency": "emergency"}[state["route"]]
