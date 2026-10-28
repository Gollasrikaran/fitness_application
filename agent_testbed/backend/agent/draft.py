"""Plan drafting: turn an assessment into a draft for the doctor (BUILD_PLAN.md,
phase 5). Run when a doctor clicks "Generate plan".

  severe      a "doctor must write the plan" item: no exercises, no AI
  not severe  the AI picks and orders exercises from store.plans.candidates()
              (the ones the safety grid allows for every condition) and
              writes the reasons. Code sets the doses, never the AI, and
              store.plans.violations() checks the draft.
  fallback    if the AI fails or breaks a rule, the rule-built
              store.plans.starter_exercises() draft is used instead.

A new draft replaces the patient's pending one. For a patient who already
has an approved plan it is an "update", listing what changes; once approved
it becomes the plan the patient sees. Nothing reaches the patient until a
doctor approves it.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agent.assess import run_assessment
from agent.llm import chat_model
from agent.prompts import DRAFT
from app import clinic
from store import plans as plan_store
from store.db import session
from store.models import PlanProposal

log = logging.getLogger("agent.draft")

MIN_EXERCISES = 3


class AIPick(BaseModel):
    activity_type: str
    why: str = Field(description="One line for the doctor")


class AIDraft(BaseModel):
    exercises: list[AIPick]
    instructions: str
    reason: str


def _ask_ai(assessment: dict, patient: dict, allowed: list[dict]) -> AIDraft:
    lines = "\n".join(f"- {e['activity_type']}: {e['name']}, {e['sets']} x {e['amount']:g} {e['unit']}"
                      + (f" (CAUTION: {e['notes']})" if e["notes"] else "") for e in allowed)
    high = min(plan_store.MAX_EXERCISES, len(allowed))
    prompt = DRAFT.format(allowed=lines, low=min(MIN_EXERCISES, high), high=high)
    about = {**patient, "problem": assessment["problem"], "body_area": assessment["body_area"],
             "conditions": [{"code": c["code"], "name": c["name"]} for c in assessment["conditions"]],
             "concerns": assessment["concerns"]}
    model = chat_model(temperature=0, max_tokens=800).with_structured_output(AIDraft)
    return model.invoke([SystemMessage(content=prompt),
                         HumanMessage(content="PATIENT\n" + json.dumps(about, ensure_ascii=False, default=str))])


def _from_ai(answer: AIDraft, allowed: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """The AI's picks at the rules' doses. Returns (exercises, why lines,
    problems). A pick outside the allowed list is a problem, never fixed up."""
    by_type = {e["activity_type"]: e for e in allowed}
    exercises, whys, problems = [], [], []
    for pick in answer.exercises:
        e = by_type.get(pick.activity_type)
        if e is None:
            problems.append(f"{pick.activity_type}: not allowed for this patient")
        elif any(x["activity_type"] == e["activity_type"] for x in exercises):
            problems.append(f"{e['name']}: listed twice")
        else:
            exercises.append(plan_store.plan_entry(e))
            whys.append(f"- {e['name']}: {pick.why.strip()}")
    if not exercises and not problems:
        problems.append("no exercises picked")
    if not answer.instructions.strip():
        problems.append("no instructions for the patient")
    return exercises, whys, problems


def build_draft(db: Session, patient_id: str, assessment: dict, patient: dict,
                ask_ai: Callable[[dict, dict, list[dict]], AIDraft] = _ask_ai) -> PlanProposal:
    """Save and return the draft for one assessment. `patient` is
    {age, sex, bmi}."""
    codes = assessment["codes"]
    names = plan_store.condition_names(db, codes)
    label = ", ".join(names.get(c, c) for c in codes)
    current = plan_store.latest_plan(db, patient_id)
    plan_store.pending_superseded(db, patient_id)

    def save(source: str, exercises: list[dict], instructions: str, reason: str) -> PlanProposal:
        proposal = PlanProposal(
            patient_id=patient_id, assessment_id=assessment["id"], kind="update" if current else "starter",
            source=source, instructions=instructions, exercises=exercises, reason=reason, conditions=codes,
            changes=plan_store.exercise_changes(current.exercises, exercises) if current and exercises else [],
            based_on_plan_id=current.id if current else None)
        db.add(proposal)
        db.flush()
        return proposal

    def doctor(why: list[str]) -> PlanProposal:
        lines = ["A doctor must write this plan: no AI draft.", *(f"- {w}" for w in why)]
        if current:
            lines.append("The current plan stays until you approve a new one.")
        return save("doctor", [], "", "\n".join(lines))

    if assessment["severity"] == "severe":
        return doctor(assessment["severe_reasons"])
    readings = assessment.get("readings") or {}
    allowed, profile_rules = plan_store.candidates(db, codes, patient.get("age"), patient.get("bmi"), readings)
    if not allowed:
        return doctor([f"No exercise is allowed for this patient: {label}", *profile_rules])

    try:
        answer = ask_ai(assessment, patient, allowed)
        exercises, whys, problems = _from_ai(answer, allowed)
        problems += plan_store.violations(db, exercises, codes, readings) if not problems else []
    except Exception as exc:  # the rules draft the plan instead
        log.error("Draft AI call failed for patient %s: %s", patient_id, exc)
        answer, problems = None, [f"the AI was unavailable ({type(exc).__name__})"]
    if not problems:
        reason = "\n".join([answer.reason.strip(), *whys, *profile_rules,
                            "Doses are the reviewed starting doses from the safety rules."])
        return save("ai", exercises, answer.instructions.strip(), reason)

    log.warning("AI draft not used for patient %s: %s", patient_id, "; ".join(problems))
    exercises, profile_rules = plan_store.starter_exercises(db, codes, patient.get("age"), patient.get("bmi"), readings=readings)
    broken = plan_store.violations(db, exercises, codes, readings)
    if broken or not exercises:  # can't happen with a consistent grid; never save a broken draft
        log.error("Rule draft broke the rules for patient %s: %s", patient_id, "; ".join(broken))
        return doctor([f"The rules could not build a safe draft: {'; '.join(broken) or 'no exercises'}"])
    reason = "\n".join([f"AI draft not used: {'; '.join(problems)}.",
                        f"Exercises chosen by the safety grid for: {label}.", *profile_rules])
    return save("rules", exercises, f"Starter plan built from the safety rules for: {label}.", reason)


def assessment_age(patient: dict) -> int | None:
    return patient.get("age")


def generate_plan(patient_id: str, doctor_id: str) -> dict:
    """The doctor's "Generate plan": assess the patient, then draft. Returns
    {"assessment", "draft"}; the draft waits for the doctor's review."""
    context = clinic.patient_context(patient_id)
    if context is None:
        raise ValueError("Patient not found")
    assessment = run_assessment(patient_id, doctor_id, context=context)
    patient = {"age": context["patient"]["age"], "sex": context["patient"]["sex"], "bmi": context["body"]["bmi"]}
    with session() as db:
        draft = build_draft(db, patient_id, assessment, patient)
        return {"assessment": assessment, "draft": plan_store.proposal_dict(draft, full=True)}
