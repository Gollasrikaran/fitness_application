"""Exercise plans drafted by fixed rules, never by the AI. Ported from
medical_agent/backend/app/agent/plans.py (see medical_agent/EXERCISE_ALLOCATION.md).

Every draft is a PlanProposal that waits for a doctor. Only an approved one
becomes a Plan, which is what the patient sees and follows.

  starter  first plan: safety-grid exercises for all the patient's
           conditions, most useful first, at the reviewed default doses.
  update   the patient's conditions in the record changed: exercises a new
           condition rules out leave the plan; safe ones take their place.

Conditions come from the clinic record (agent.conditions), not checkboxes.
Plans never get harder on their own. A "refer" condition gets no rule-built
draft: the proposal asks the doctor to write the plan.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from store.models import Condition, Exercise, Plan, PlanProposal, SafetyRule

EXERCISES_BY_EXPERIENCE = {"beginner": 4, "intermediate": 5, "active": 7}
# The clinic record doesn't say how active someone is: start everyone as a
# beginner (the most moderate plan). The doctor can add more.
DEFAULT_EXPERIENCE = "beginner"

# PROVISIONAL thresholds so we can build; the doctor confirms or replaces them.
OLDER_AGE = 60         # at or above: high-impact exercises left out, doses one step lower
HIGH_BMI = 30.0        # at or above: high-impact exercises left out
HIGH_IMPACT = {"running"}


# ── Reading ─────────────────────────────────────────────────────────────────

def latest_plan(db: Session, patient_id: str) -> Plan | None:
    return db.scalars(select(Plan).where(Plan.patient_id == patient_id)
                      .order_by(Plan.created_at.desc()).limit(1)).first()


def pending_proposal(db: Session, patient_id: str) -> PlanProposal | None:
    return db.scalars(select(PlanProposal).where(PlanProposal.patient_id == patient_id,
                                                 PlanProposal.status == "pending")
                      .order_by(PlanProposal.created_at.desc()).limit(1)).first()


def plan_dict(p: Plan | None) -> dict | None:
    if p is None:
        return None
    return {"id": p.id, "doctor_id": p.doctor_id, "instructions": p.instructions, "exercises": p.exercises,
            "conditions": p.conditions, "given_on": p.created_at.date().isoformat()}


def proposal_dict(p: PlanProposal | None, full: bool = False) -> dict | None:
    if p is None:
        return None
    out = {"id": p.id, "kind": p.kind, "source": p.source, "status": p.status,
           "requested_on": p.created_at.date().isoformat()}
    if full:  # for the doctor; the patient only sees the status
        out |= {"instructions": p.instructions, "exercises": p.exercises, "changes": p.changes,
                "reason": p.reason, "conditions": p.conditions, "patient_note": p.patient_note,
                "review_note": p.review_note}
    return out


# ── The rules ───────────────────────────────────────────────────────────────

def approved_exercises(db: Session, codes: list[str]) -> list[dict]:
    """Exercises allowed for *every* condition. Fails closed: a "refer"
    condition allows nothing; a missing rule means not approved; "avoid" for
    any condition excludes it; "modify" carries its note along."""
    conditions = db.scalars(select(Condition).where(Condition.code.in_(codes))).all()
    if not conditions or any(c.bucket == "refer" for c in conditions):
        return []
    rules: dict[str, dict[str, SafetyRule]] = defaultdict(dict)
    for rule in db.scalars(select(SafetyRule).where(SafetyRule.condition_code.in_(codes))):
        rules[rule.activity_type][rule.condition_code] = rule
    approved = []
    for ex in db.scalars(select(Exercise).order_by(Exercise.display_name)):
        by_condition = rules.get(ex.activity_type, {})
        if set(by_condition) != set(codes) or any(r.verdict == "avoid" for r in by_condition.values()):
            continue
        notes = [r.note for r in by_condition.values() if r.verdict == "modify" and r.note]
        approved.append({"activity_type": ex.activity_type, "display_name": ex.display_name,
                         "unit": ex.amount_unit, "default_sets": ex.default_sets,
                         "default_amount": ex.default_amount, "verdict": "modify" if notes else "safe",
                         "notes": notes})
    return approved


def _usefulness(db: Session, codes: list[str]) -> dict[str, int]:
    """Best (lowest) rank per exercise across the patient's conditions."""
    rows = db.execute(select(SafetyRule.activity_type, func.min(SafetyRule.usefulness_rank))
                      .where(SafetyRule.condition_code.in_(codes), SafetyRule.verdict != "avoid",
                             SafetyRule.usefulness_rank.is_not(None))
                      .group_by(SafetyRule.activity_type)).all()
    return dict(rows)


def starter_exercises(db: Session, codes: list[str], age: int | None, bmi: float | None,
                      experience: str = DEFAULT_EXPERIENCE) -> tuple[list[dict], list[str]]:
    """The exercises, and a line per provisional profile rule that changed them."""
    approved = approved_exercises(db, codes)
    ranks = _usefulness(db, codes)
    by_type = {e.activity_type: e for e in db.scalars(select(Exercise))}
    rules: list[str] = []
    older = age is not None and age >= OLDER_AGE
    if older or (bmi is not None and bmi >= HIGH_BMI):
        dropped = [e["display_name"] for e in approved if e["activity_type"] in HIGH_IMPACT]
        approved = [e for e in approved if e["activity_type"] not in HIGH_IMPACT]
        if dropped:
            why = f"age {age} >= {OLDER_AGE}" if older else f"BMI {bmi} >= {HIGH_BMI:g}"
            rules.append(f"{', '.join(dropped)} left out: {why} (provisional rule)")
    # "safe" before "modify": a starter plan stays moderate.
    approved.sort(key=lambda e: (e["verdict"] == "modify", ranks.get(e["activity_type"], 99),
                                 by_type[e["activity_type"]].priority_order))
    count = EXERCISES_BY_EXPERIENCE.get(experience, EXERCISES_BY_EXPERIENCE["beginner"])
    exercises = []
    for e in approved[:count]:
        amount, step = e["default_amount"], by_type[e["activity_type"]].progression_step
        if older and amount - step >= step - 1e-9:
            amount = round(amount - step, 2)
        exercises.append({"activity_type": e["activity_type"], "name": e["display_name"], "unit": e["unit"],
                          "sets": e["default_sets"], "amount": amount, "notes": " ".join(e["notes"])})
    if older and exercises:
        rules.append(f"Doses one step below the defaults: age {age} >= {OLDER_AGE} (provisional rule)")
    return exercises, rules


def _names(db: Session, codes: list[str]) -> dict[str, str]:
    return {c.code: c.display_name for c in db.scalars(select(Condition).where(Condition.code.in_(codes)))}


def _needs_doctor(db: Session, codes: list[str]) -> str:
    refer = [c.display_name for c in db.scalars(select(Condition).where(Condition.code.in_(codes)))
             if c.bucket == "refer"]
    return ("Needs a doctor-written plan: " + (", ".join(refer) if refer else "no exercise is approved for "
            "every condition") + ". The rules can't draft one.")


def _replace_pending(db: Session, patient_id: str, proposal: PlanProposal) -> PlanProposal:
    """Swap in a fresh draft, unless the pending one already says the same."""
    pending = pending_proposal(db, patient_id)
    if pending is not None:
        if (pending.kind, pending.source, pending.exercises) == (proposal.kind, proposal.source, proposal.exercises):
            return pending
        pending.status = "superseded"
    db.add(proposal)
    db.flush()
    return proposal


# ── What the agent calls ────────────────────────────────────────────────────

def request_plan(db: Session, patient_id: str, codes: list[str], age: int | None,
                 bmi: float | None) -> tuple[str, PlanProposal | None]:
    """Draft a first plan. Returns (status, proposal):
    "has_plan" | "pending" (already waiting) | "drafted"."""
    if latest_plan(db, patient_id) is not None:
        return "has_plan", None
    pending = pending_proposal(db, patient_id)
    if pending is not None:
        return "pending", pending
    names = _names(db, codes)
    label = ", ".join(names.get(c, c) for c in codes)
    exercises, rules = starter_exercises(db, codes, age, bmi)
    if exercises:
        source, instructions = "rules", f"Starter plan built from the safety rules for: {label}."
        reason = "\n".join([f"Exercises chosen by the safety grid for: {label}.", *rules])
    else:
        source, instructions, reason = "doctor", "", _needs_doctor(db, codes)
    proposal = PlanProposal(patient_id=patient_id, kind="starter", source=source, instructions=instructions,
                            exercises=exercises, changes=[], reason=reason, conditions=codes)
    db.add(proposal)
    db.flush()
    return "drafted", proposal


def sync_conditions(db: Session, patient_id: str, codes: list[str], age: int | None,
                    bmi: float | None) -> PlanProposal | None:
    """The record's conditions changed since the current plan was made:
    draft an update for the doctor. Not called yet: the doctor's "Generate
    plan" (BUILD_PLAN.md, phase 5) will use it for a patient who has a plan."""
    plan = latest_plan(db, patient_id)
    if plan is None or set(plan.conditions) == set(codes):
        return None
    pending = pending_proposal(db, patient_id)
    if pending is not None and pending.kind == "update" and set(pending.conditions) == set(codes):
        return pending  # already drafted for these conditions
    added = [c for c in codes if c not in plan.conditions]
    removed = [c for c in plan.conditions if c not in codes]
    names = _names(db, list(set(codes) | set(plan.conditions)))
    what = "; ".join(filter(None, ["added " + ", ".join(names.get(c, c) for c in added) if added else "",
                                   "removed " + ", ".join(names.get(c, c) for c in removed) if removed else ""]))
    reason = f"Conditions in the record changed ({what})."
    base = plan.exercises

    if any(c.bucket == "refer" for c in db.scalars(select(Condition).where(Condition.code.in_(codes)))):
        return _replace_pending(db, patient_id, PlanProposal(
            patient_id=patient_id, kind="update", source="doctor", instructions="", exercises=[], changes=[],
            reason=f"{reason} {_needs_doctor(db, codes)} The current plan stays until you replace it.",
            conditions=codes, based_on_plan_id=plan.id))

    # Only a newly added condition can rule out an exercise the doctor chose.
    verdicts: dict[str, dict[str, str]] = defaultdict(dict)
    for r in db.scalars(select(SafetyRule).where(SafetyRule.condition_code.in_(added))):
        verdicts[r.activity_type][r.condition_code] = r.verdict
    exercises, changes = [], []
    for e in base:
        blocked = [c for c in added if verdicts[e["activity_type"]].get(c, "avoid") == "avoid"]
        if blocked:
            changes.append({"activity_type": e["activity_type"], "name": e["name"],
                            "from": {"sets": e["sets"], "amount": e["amount"]}, "to": None,
                            "note": "Removed: not safe with " + ", ".join(names.get(c, c) for c in blocked)})
        else:
            exercises.append(dict(e))
    picks, rules = starter_exercises(db, codes, age, bmi)
    for e in picks:
        if len(exercises) >= len(base):
            break
        if e["activity_type"] not in {x["activity_type"] for x in exercises}:
            exercises.append(e)
            changes.append({"activity_type": e["activity_type"], "name": e["name"], "from": None,
                            "to": {"sets": e["sets"], "amount": e["amount"]},
                            "note": "Added in place of a removed exercise"})
    if not changes:
        plan.conditions = codes  # nothing in the plan is affected: just remember the new conditions
        return None
    return _replace_pending(db, patient_id, PlanProposal(
        patient_id=patient_id, kind="update", source="rules", exercises=exercises, changes=changes,
        instructions=f"Your plan, updated for your conditions.\n{plan.instructions}",
        reason="\n".join([reason, *rules]), conditions=codes, based_on_plan_id=plan.id))


# ── Doctor review ───────────────────────────────────────────────────────────

def approve(db: Session, proposal: PlanProposal, doctor_id: str, instructions: str | None,
            exercises: list[dict] | None, note: str | None) -> Plan:
    plan = Plan(patient_id=proposal.patient_id, doctor_id=doctor_id,
                instructions=instructions or proposal.instructions,
                exercises=proposal.exercises if exercises is None else exercises,
                conditions=proposal.conditions, proposal_id=proposal.id)
    db.add(plan)
    db.flush()
    proposal.status, proposal.approved_plan_id = "approved", plan.id
    _reviewed(proposal, doctor_id, note)
    return plan


def reject(proposal: PlanProposal, doctor_id: str, note: str) -> None:
    proposal.status = "rejected"
    _reviewed(proposal, doctor_id, note)


def _reviewed(proposal: PlanProposal, doctor_id: str, note: str | None) -> None:
    proposal.reviewed_by, proposal.review_note = doctor_id, note
    proposal.reviewed_at = datetime.now(timezone.utc)
