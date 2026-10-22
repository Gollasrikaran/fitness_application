from typing import Annotated, Literal, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # ── Conversation ─────────────────────────────────────────────
    messages: Annotated[list, add_messages]   # chat history; the last AI message is the reply

    # ── Who is talking, about whom ───────────────────────────────
    mode: Literal["patient", "doctor"]        # from the toggle in the testbed
    patient_id: str                           # clinic patient.id
    doctor_id: str | None                     # set in doctor mode

    # ── What the agent knows (filled by load_context, no AI) ────
    context: dict                             # clinic.patient_context(patient_id), see FEATURES.txt
    conditions: list[str]                     # context mapped to our condition codes, e.g. ["bp_controlled", "arthritis_knee"]

    # ── Safety (filled by safety_screen, fixed rules, no AI) ────
    red_flags: list[str]                      # red_flags.scan(message): e.g. ["chest_pain"]
    forced_reasons: list[str]                 # hard rules that require a doctor, e.g. "Red flag: Fever"

    # ── Supervisor's decision ────────────────────────────────────
    condition_severity: Literal["normal", "hard"]                # from the patient's context
    request_severity: Literal["normal", "hard", "emergency"]     # from this message
    intent: Literal["question", "symptom", "plan_request", "plan_too_hard", "other"]
    route: Literal["chat", "clarify", "plan", "doctor", "emergency"]
    reason: str                               # one line explaining the route, shown to the doctor

    # ── Plans (rule-based engine, always needs a doctor) ────────
    plan_draft: dict | None                   # draft from plans.py, waiting for doctor approval
    pain_score: int | None                    # pain the patient stated in this message, 0-10

    # ── Hand-off to the doctor ───────────────────────────────────
    case: dict | None                         # doctor case opened or updated this turn
