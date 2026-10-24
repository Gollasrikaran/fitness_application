"""Exercise plans: the safety rules every draft must follow, and the doctor's
review. Ported from medical_agent/backend/app/agent/plans.py (see
medical_agent/EXERCISE_ALLOCATION.md). agent.draft turns an assessment into
a draft using what is here.

Every draft is a PlanProposal that waits for a doctor. Only an approved one
becomes a Plan, which is what the patient sees and follows.

- candidates(): the exercises the safety grid allows for *all* the patient's
  conditions, most useful first, at the reviewed starting doses.
- starter_exercises(): the rule-built plan (no AI), the fallback when the
  AI can't draft one.
- violations(): why a draft breaks the rules. Every draft is checked before
  it is saved.

Plans never get harder on their own. A "refer" condition allows no exercise:
the doctor writes the plan.
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
MAX_EXERCISES = 5      # in any draft the agent makes


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
    out = {"id": p.id, "kind": p.kind, "source": p.source, "status": p.status, "assessment_id": p.assessment_id,
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


def candidates(db: Session, codes: list[str], age: int | None,
               bmi: float | None) -> tuple[list[dict], list[str]]:
    """Every exercise allowed for this patient, most suitable first, at its
    starting dose; and a line per provisional profile rule that changed them.
    Entries: {activity_type, name, unit, sets, amount, notes, verdict}."""
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
    out = []
    for e in approved:
        amount, step = e["default_amount"], by_type[e["activity_type"]].progression_step
        if older and amount - step >= step - 1e-9:
            amount = round(amount - step, 2)
        out.append({"activity_type": e["activity_type"], "name": e["display_name"], "unit": e["unit"],
                    "sets": e["default_sets"], "amount": amount, "notes": " ".join(e["notes"]),
                    "verdict": e["verdict"]})
    if older and out:
        rules.append(f"Doses one step below the defaults: age {age} >= {OLDER_AGE} (provisional rule)")
    return out, rules


def plan_entry(e: dict) -> dict:
    """An exercise as it is stored in a plan."""
    return {k: e[k] for k in ("activity_type", "name", "unit", "sets", "amount", "notes")}


def starter_exercises(db: Session, codes: list[str], age: int | None, bmi: float | None,
                      experience: str = DEFAULT_EXPERIENCE) -> tuple[list[dict], list[str]]:
    """The rule-built plan (no AI), and a line per provisional profile rule
    that changed it."""
    allowed, rules = candidates(db, codes, age, bmi)
    count = EXERCISES_BY_EXPERIENCE.get(experience, EXERCISES_BY_EXPERIENCE["beginner"])
    return [plan_entry(e) for e in allowed[:count]], rules


def violations(db: Session, exercises: list[dict], codes: list[str]) -> list[str]:
    """Why a draft breaks the safety rules; empty when it doesn't. Fails
    closed: an unknown exercise or condition, a missing rule, "avoid" for any
    condition, a "refer" condition, or a dose outside 1..max is a violation."""
    problems = []
    conditions = {c.code: c for c in db.scalars(select(Condition).where(Condition.code.in_(codes)))}
    if not codes or set(codes) - set(conditions):
        problems.append(f"unknown condition codes: {sorted(set(codes) - set(conditions)) or 'none given'}")
    refer = [c.display_name for c in conditions.values() if c.bucket == "refer"]
    if refer and exercises:
        problems.append(f"exercises drafted for a condition that needs a doctor: {', '.join(refer)}")
    if len(exercises) > MAX_EXERCISES:
        problems.append(f"{len(exercises)} exercises: at most {MAX_EXERCISES}")
    by_type = {e.activity_type: e for e in db.scalars(select(Exercise))}
    verdicts: dict[str, dict[str, str]] = defaultdict(dict)
    for r in db.scalars(select(SafetyRule).where(SafetyRule.condition_code.in_(codes))):
        verdicts[r.activity_type][r.condition_code] = r.verdict
    seen = set()
    for x in exercises:
        kind = x.get("activity_type")
        ex = by_type.get(kind)
        if ex is None:
            problems.append(f"{kind}: not one of our exercises")
            continue
        if kind in seen:
            problems.append(f"{ex.display_name}: listed twice")
        seen.add(kind)
        for code in codes:
            verdict = verdicts[kind].get(code)
            if verdict in (None, "avoid"):
                problems.append(f"{ex.display_name}: {verdict or 'no safety rule'} for {code}")
        sets, amount = x.get("sets"), x.get("amount")
        if isinstance(sets, bool) or not isinstance(sets, int) or not 1 <= sets <= ex.max_sets:
            problems.append(f"{ex.display_name}: {sets} sets (allowed 1 to {ex.max_sets})")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 < amount <= ex.max_amount:
            problems.append(f"{ex.display_name}: {amount} {ex.amount_unit} (allowed up to {ex.max_amount:g})")
    return problems


def condition_names(db: Session, codes: list[str]) -> dict[str, str]:
    return {c.code: c.display_name for c in db.scalars(select(Condition).where(Condition.code.in_(codes)))}


def pending_superseded(db: Session, patient_id: str) -> None:
    """A new draft replaces the one waiting for review."""
    pending = pending_proposal(db, patient_id)
    if pending is not None:
        pending.status = "superseded"


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
