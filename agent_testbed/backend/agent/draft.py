"""Plan drafting: turn an assessment into a draft for the doctor (BUILD_PLAN.md,
phase 5). Run when a doctor clicks "Generate plan".

  severe      a "doctor must write the plan" item: no exercises, no AI
  not severe  a balanced plan (store.plans.plan_slots, 2026-11-16): walking
              first, then leg strength, upper-body strength, balance and
              breathing, each from the exercises the safety grid allows for
              every condition. The AI picks one of each slot's best few and
              writes the reasons. Code sets the doses and the order, never
              the AI, and store.plans.violations() checks the draft.
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
from app.source import clinic
from store import plans as plan_store
from store.db import session
from store.models import PlanProposal

log = logging.getLogger("agent.draft")


class AIPick(BaseModel):
    activity_type: str
    why: str = Field(description="One line for the doctor")


class AIDraft(BaseModel):
    exercises: list[AIPick]
    instructions: str
    reason: str


def _option(e: dict) -> str:
    return (f"{e['activity_type']}: {e['name']}, {e['sets']} x {e['amount']:g} {e['unit']}"
            + (f" (CAUTION: {e['notes']})" if e["notes"] else ""))


def _ask_ai(assessment: dict, patient: dict, allowed: list[dict]) -> AIDraft:
    slots = plan_store.plan_slots(allowed)
    lines = "\n".join(f"{i}. {name}:\n" + "\n".join(f"   - {_option(e)}" + ("  [best fit]" if j == 0 else "")
                                                  for j, e in enumerate(options))
                      for i, (name, options) in enumerate(slots, 1))
    core = plan_store.core_exercise(allowed)
    core_line = (f"CORE: {core['activity_type']} ({core['name']}) is the main exercise of the plan; the rules put it "
                 f"first themselves. Don't return it or any other of {', '.join(plan_store.CORE_AEROBIC)}.\n"
                 if core else "")
    prompt = DRAFT.format(slots=lines, core=core_line, count=len(slots))
    about = {**patient, "problem": assessment["problem"], "body_area": assessment["body_area"],
             "conditions": [{"code": c["code"], "name": c["name"]} for c in assessment["conditions"]],
             "concerns": assessment["concerns"]}
    model = chat_model(temperature=0, max_tokens=800).with_structured_output(AIDraft)
    return model.invoke([SystemMessage(content=prompt),
                         HumanMessage(content="PATIENT\n" + json.dumps(about, ensure_ascii=False, default=str))])


def _key(text: str) -> str:
    """"Sit to Stand", "sit_to_stand", "sit-to-stand" -> "sittostand"."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


CORE_WHY = "the main everyday exercise of the plan (always first, set by the safety rules)."
SLOT_WHY = "the best fit for the patient's conditions in this part of the plan (chosen by the safety rules)."


def _from_ai(answer: AIDraft, allowed: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """The balanced plan with the AI's choice in each slot, at the rules'
    doses (store.plans.balanced_plan). Returns (exercises, why lines,
    problems). A pick that is no option of any slot, or a second pick for one
    slot, is a problem, never fixed up; a slot the AI left out gets its best
    fit. The order is the plan's: walking first, breathing last."""
    slots = plan_store.plan_slots(allowed)
    slot_of = {e["activity_type"]: name for name, options in slots for e in options}
    core = plan_store.core_exercise(allowed)
    # The AI sometimes writes the name instead of the id ("walking" for walk,
    # 6959e408 on 2026-11-16): an exercise's name means that exercise.
    by_name = {_key(e["name"]): e["activity_type"] for e in allowed}
    picks, whys, problems = {}, {}, []
    for pick in answer.exercises:
        kind = pick.activity_type.strip()
        kind = kind if kind in slot_of or kind in plan_store.CORE_AEROBIC else by_name.get(_key(kind), kind)
        if core and kind == core["activity_type"]:
            whys[kind] = pick.why.strip()
        elif kind in plan_store.CORE_AEROBIC:
            continue  # another walking-type exercise: the core already covers it
        elif kind not in slot_of:
            problems.append(f"{kind}: not one of the options for this patient")
        elif slot_of[kind] in picks:
            problems.append(f"{kind}: a second pick for the {slot_of[kind]} part of the plan")
        else:
            picks[slot_of[kind]] = kind
            whys[kind] = pick.why.strip()
    if not answer.exercises:
        problems.append("no exercises picked")
    if not answer.instructions.strip():
        problems.append("no instructions for the patient")
    chosen = plan_store.balanced_plan(allowed, picks)
    lines = [f"- {e['name']}: {whys.get(e['activity_type']) or (CORE_WHY if e is core else SLOT_WHY)}"
             for e in chosen]
    return [plan_store.plan_entry(e) for e in chosen], lines, problems


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
        if patient.get("eligibility_note"):  # information for the doctor only: it never changes the draft
            reason = f"{patient['eligibility_note']}\n{reason}"
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


def eligibility_note(context: dict) -> str | None:
    """The "can exercise" screening (Patient Intelligence API), when it says
    no: a note for the doctor, with the screening's own reason. It is research
    on who benefits from exercise, not a safety check: it never withholds the
    draft (decided 2026-11-03). The clinic DB source has no such check."""
    summary = context.get("clinical_summary") or {}
    if summary.get("exercise_suitable") is not False:
        return None
    reason = (summary.get("exercise_reason") or "").strip()
    return (f"Note: the exercise screening (research, not a safety check) marks this patient not suitable "
            f"for exercise (main type: {summary.get('patient_type') or 'not given'})."
            + (f" Its reason: {reason}." if reason else "") + " Please check before approving.")


def patient_profile(context: dict) -> dict:
    """What the draft needs about the patient: {age, sex, bmi, eligibility_note}."""
    return {"age": context["patient"]["age"], "sex": context["patient"]["sex"], "bmi": context["body"]["bmi"],
            "eligibility_note": eligibility_note(context)}


def generate_plan(patient_id: str, doctor_id: str, reading_days: int = plan_store.READING_DAYS) -> dict:
    """The doctor's "Generate plan": assess the patient, then draft. Returns
    {"assessment", "draft"}; the draft waits for the doctor's review.
    `reading_days`: how far back readings count (the doctor's choice)."""
    context = clinic.patient_context(patient_id)
    if context is None:
        raise ValueError("Patient not found")
    assessment = run_assessment(patient_id, doctor_id, context=context, reading_days=reading_days)
    with session() as db:
        draft = build_draft(db, patient_id, assessment, patient_profile(context))
        return {"assessment": assessment, "draft": plan_store.proposal_dict(draft, full=True)}
