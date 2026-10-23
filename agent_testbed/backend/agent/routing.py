"""Safety rules that decide, whatever the AI says. Plain code, no AI.

The rules can only escalate: a reason here sends the patient to a doctor.
"""
from __future__ import annotations

from agent.conditions import REFER


def condition_floor(state: dict) -> list[str]:
    """Reasons the patient's condition needs a doctor, whatever the AI says."""
    ctx = state["context"]
    reasons = [f"Condition needs a doctor: {c}" for c in state.get("conditions", []) if c in REFER]
    reasons += [f"Critical vital: {f['code']} = {f['value']} on {f['date']}"
                for f in ctx["vital_flags"] if f["severity"] == "CRITICAL"]
    reasons += [f"Emergency visit on {e['date']}" for e in ctx["alerts"]["emergencies"]]
    return reasons
