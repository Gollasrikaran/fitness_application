from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # ── Conversation ─────────────────────────────────────────────
    messages: Annotated[list, add_messages]   # chat history; the last AI message is the reply

    # ── Who is asking, about whom ────────────────────────────────
    patient_id: str                           # clinic patient.id
    doctor_id: str                            # the doctor asking (clinic user.id)

    # ── What the agent knows (filled by load_context, no AI) ────
    context: dict                             # clinic.patient_context(patient_id), see FEATURES.txt
    conditions: list[str]                     # context mapped to our condition codes, e.g. ["bp_controlled", "arthritis_knee"]
