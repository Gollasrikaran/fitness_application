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
import re
from collections.abc import Callable

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.assess import run_assessment
from agent.llm import ask_structured
from agent.prompts import DRAFT
from app.source import clinic
from store import plans as plan_store
from store.db import session
from store.models import Condition, PlanProposal

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
            + (f" (CAUTION: {e['notes']})" if e["notes"] else "")
            + (f" (EVIDENCE: {'; '.join(e['benefits'])})" if e.get("benefits") else ""))


def _ask_ai(assessment: dict, patient: dict, allowed: list[dict]) -> AIDraft:
    slots = plan_store.plan_slots(allowed)
    lines = "\n".join(f"{i}. {name} (return one activity_type from this list, not the part's name):\n"
                      + "\n".join(f"   - {_option(e)}" + ("  [best fit]" if j == 0 else "")
                                  for j, e in enumerate(options))
                      for i, (name, options) in enumerate(slots, 1))
    core = plan_store.core_exercise(allowed)
    core_line = (f"CORE: {core['activity_type']} ({core['name']}) is the main exercise of the plan; the rules put it "
                 f"first themselves. Return it once, with its why"
                 + (f" (EVIDENCE: {'; '.join(core['benefits'])})" if core.get("benefits") else "")
                 + f"; return no other of {', '.join(plan_store.CORE_AEROBIC)}.\n" if core else "")
    prompt = DRAFT.format(slots=lines, core=core_line, count=len(slots))
    about = patient_for_ai(assessment, patient)
    return ask_structured(prompt, "PATIENT\n" + json.dumps(about, ensure_ascii=False, default=str), AIDraft)


def patient_for_ai(assessment: dict, patient: dict) -> dict:
    """What the draft AI reads about the patient. The assessment's medicine
    notes ("Medicine: ...") are left out: they are for the doctor only, and
    the plan is never chosen or explained by medicines (6959e408, 2026-11-18:
    the AI justified a balance exercise with cetirizine's drowsiness)."""
    return {**patient, "problem": assessment["problem"], "body_area": assessment["body_area"],
            "conditions": [{"code": c["code"], "name": c["name"]} for c in assessment["conditions"]],
            "concerns": [c for c in assessment["concerns"] if not c.lower().startswith("medicine:")]}


def _key(text: str) -> str:
    """"Sit to Stand", "sit_to_stand", "sit-to-stand" -> "sittostand"."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


CORE_WHY = "Main exercise of the plan, always first (set by the safety rules)."
SLOT_WHY = "{slot}: the best-ranked option for this part of the plan (chosen by the safety rules)."
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    """"4-7 mmHg", "0.5%" -> {"4", "7", "0.5"}; "4.0" and "4" are the same."""
    return {f"{float(n):g}" for n in _NUMBER.findall(text or "")}


def _why(e: dict, slot: str | None, ai_line: str | None, known: set[str] = frozenset()) -> str:
    """The exercise's "why" for the doctor (plan C, 2026-11-17). The AI writes
    it, with our research (data/exercise_benefits.csv, the option's EVIDENCE)
    as its only source of health facts. Every number in the AI's line must
    be in that evidence or the patient's own data (`known`: age, BMI);
    otherwise the line is dropped as possibly invented. Without a usable AI
    line: our research line, else the rules' standard line."""
    evidence = "; ".join(e.get("benefits") or [])
    if ai_line and _numbers(ai_line) <= _numbers(evidence) | set(known):
        return ai_line
    if evidence:
        return evidence + "."
    return CORE_WHY if slot is None else SLOT_WHY.format(slot=slot.capitalize())


def _from_ai(answer: AIDraft, allowed: list[dict], known: set[str] = frozenset()
             ) -> tuple[list[dict], list[str]]:
    """The balanced plan with the AI's choice in each slot, at the rules'
    doses (store.plans.balanced_plan). Returns (exercises, problems); each
    exercise carries its own "why" for the doctor (shown under the exercise
    since 2026-11-17, no longer in the draft's reason; see _why). A pick that
    is no option of any slot, or a second pick for one slot, is a problem,
    never fixed up; a slot the AI left out gets its best fit. The order is
    the plan's: walking first, breathing last."""
    slots = plan_store.plan_slots(allowed)
    slot_of = {e["activity_type"]: name for name, options in slots for e in options}
    core = plan_store.core_exercise(allowed)
    # The AI sometimes writes the name instead of the id ("walking" for walk,
    # 6959e408 on 2026-11-16): an exercise's name means that exercise.
    by_name = {_key(e["name"]): e["activity_type"] for e in allowed}
    # The AI sometimes writes the part's name instead ("leg strength",
    # 6959e408 on 2026-11-17): that part's best fit, which the rules would
    # have chosen anyway.
    by_name |= {_key(name): options[0]["activity_type"] for name, options in slots}
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
    return [{**plan_store.plan_entry(e),
             "why": _why(e, None if e is core else slot_of.get(e["activity_type"]), whys.get(e["activity_type"]),
                         known)}
            for e in chosen], problems


def _rules_whys(exercises: list[dict], allowed: list[dict]) -> list[dict]:
    """A rules draft's exercises with their "why" too (2026-11-17): our
    research line, else the rules' standard line (there is no AI line)."""
    by_type = {e["activity_type"]: e for e in allowed}
    slot_of = {e["activity_type"]: name for name, options in plan_store.plan_slots(allowed) for e in options}
    core = plan_store.core_exercise(allowed)
    return [{**x, "why": _why(by_type.get(x["activity_type"], {}),
                              None if core and x["activity_type"] == core["activity_type"]
                              else slot_of.get(x["activity_type"], "other"), None)}
            for x in exercises]


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
        # The conditions' notes (e.g. the skin advice), so the patient's instructions carry them.
        notes = {c.display_name: c.notes for c in db.scalars(select(Condition).where(Condition.code.in_(codes)))
                 if c.notes and c.code not in ("none", "other_unlisted")}
        answer = ask_ai(assessment, {**patient, "condition_notes": notes} if notes else patient, allowed)
        known = _numbers(" ".join(str(patient.get(k) or "") for k in ("age", "bmi")))  # the AI may quote these
        exercises, problems = _from_ai(answer, allowed, known)
        problems += plan_store.violations(db, exercises, codes, readings) if not problems else []
    except Exception as exc:  # the rules draft the plan instead
        log.error("Draft AI call failed for patient %s: %s", patient_id, exc)
        answer, problems = None, [f"the AI was unavailable ({type(exc).__name__})"]
    if not problems:
        reason = "\n".join([answer.reason.strip(), *profile_rules,
                            "Doses are the reviewed starting doses from the safety rules."])
        return save("ai", exercises, answer.instructions.strip(), reason)

    log.warning("AI draft not used for patient %s: %s", patient_id, "; ".join(problems))
    exercises, profile_rules = plan_store.starter_exercises(db, codes, patient.get("age"), patient.get("bmi"), readings=readings)
    exercises = _rules_whys(exercises, allowed)
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
