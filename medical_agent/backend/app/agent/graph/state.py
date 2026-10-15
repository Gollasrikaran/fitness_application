from typing import TypedDict



class AgentState(TypedDict):
    user_id: str
    message: str
    context: dict                 # from load_context
    history: list[dict]           # last 20 messages
    red_flags: list[str]          # from safety_screen
    forced_reasons: list[str]     # hard rules that require a doctor
    condition_severity: Literal["normal", "hard"]
    request_severity: Literal["normal", "hard", "emergency"]
    route: Literal["chat", "clarify", "doctor", "emergency", "doctor_live"]
    sources: list[dict]           # RAG passages used for the reply
    reply: str
    exercises: list[dict]
    case_id: str | None
    doctor_response: dict | None  # plan or chat, filled when the graph resumes
    new_facts: list[str]