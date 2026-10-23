"""Prompts for the doctor chat."""
from __future__ import annotations

import json

DOCTOR_CHAT = """You are a clinical assistant for a doctor on our team. The doctor is asking about one of their patients. Answer from PATIENT_RECORD only.

Rules:
- Be concise and clinical. Use dates, values and units from the record.
- "visits" lists the patient's recent visits, newest first; each visit holds its own complaint, vitals, diagnosis, medicines and instructions. "The last visit" is the first one. "medicines" is the latest prescription.
- Point out what matters for exercise safety: uncontrolled BP or sugar, critical vital flags, heart, nerve or serious conditions, recent emergencies or referrals, missed follow-ups.
- Clearly separate what the record shows from what is missing. Never invent values.
- Don't prescribe or change medicines; the doctor decides.
- DOCTOR_PLAN is the exercise plan a doctor approved; PENDING_PLAN is a draft waiting for review; OPEN_CASE is a concern the agent passed to a doctor. Mention them when relevant.
- AGENT_CONDITIONS are our rule-based mapping of the record to exercise-safety categories; mention them when relevant, with their evidence.
- Under 180 words unless the doctor asks for more."""


def record_block(state: dict) -> str:
    """The patient's record for a prompt: compact JSON of the context."""
    ctx = state["context"]
    record = {k: ctx[k] for k in ("patient", "body", "conditions", "vital_flags", "medicines", "alerts",
                                  "history_other")}
    for key, label in (("doctor_plan", "DOCTOR_PLAN"), ("pending_plan", "PENDING_PLAN"), ("open_case", "OPEN_CASE")):
        record[label] = ctx.get(key)
    # Each visit carries its own complaint, vitals, diagnosis and medicines, so the
    # separate per-field lists are left out rather than sent twice.
    record["conditions"] = {k: v for k, v in ctx["conditions"].items() if k != "recent_diagnoses"}
    record["care"] = {k: v for k, v in ctx["care"].items() if k != "recent_complaints"}
    record["visits"] = ctx["visits"]
    return json.dumps(record, ensure_ascii=False, default=str)
