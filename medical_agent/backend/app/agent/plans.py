"""Exercise plans drafted by fixed rules, never by the LLM.

Every draft is a PlanProposal that waits for a doctor. Only an approved
proposal becomes a DoctorPlan, which is what the patient sees and follows.

  starter  first plan: the safety-grid exercises for all the patient's
           conditions, most useful first, at the reviewed default doses.
  easier   the patient says their current plan is too hard: the named
           exercises (or all of them) drop one progression step.
  update   the patient's conditions changed: exercises a new condition
           rules out leave the plan and safe ones take their place.

Plans never get harder on their own; that is the doctor's call. A "refer"
condition gets no rule-built draft: the proposal asks the doctor to write it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import context as ctx
from app.agent.cases import upsert_case
from app.models import ChatMessage, Condition, DoctorPlan, Exercise, PlanProposal, SafetyRule, User

# How many exercises a starter plan holds, by the patient's stated experience.
EXERCISES_BY_EXPERIENCE = {"beginner": 4, "intermediate": 5, "active": 7}
# Pain at or above this alongside "too hard" is a clinical question, not a
# dose question: it opens a doctor case instead of drafting an easier plan.
PAIN_TO_DOCTOR = 7

# PROVISIONAL thresholds, set by the product team so we can build; the doctor
# confirms or replaces them. Every draft they touch says so to the reviewer.
OLDER_AGE = 60         # at or above: high-impact exercises left out, doses one step lower
HIGH_BMI = 30.0        # at or above: high-impact exercises left out
HIGH_IMPACT = {"running"}


def pending_proposal(db: Session, user_id: str) -> PlanProposal | None:
    return db.scalars(select(PlanProposal).where(PlanProposal.user_id == user_id,
                                                 PlanProposal.status == "pending")
                      .order_by(PlanProposal.created_at.desc()).limit(1)).first()


def supersede_pending(db: Session, user_id: str) -> None:
    for p in db.scalars(select(PlanProposal).where(PlanProposal.user_id == user_id,
                                                   PlanProposal.status == "pending")):
        p.status = "superseded"


def _usefulness(db: Session, codes: list[str]) -> dict[str, int]:
    """Best (lowest) rank per exercise across the patient's conditions."""
    rows = db.execute(select(SafetyRule.activity_type, func.min(SafetyRule.usefulness_rank))
                      .where(SafetyRule.condition_code.in_(codes), SafetyRule.verdict != "avoid",
                             SafetyRule.usefulness_rank.is_not(None))
                      .group_by(SafetyRule.activity_type)).all()
    return dict(rows)


def _bmi(profile) -> float | None:
    if profile.height_cm and profile.weight_kg:
        return round(profile.weight_kg / (profile.height_cm / 100) ** 2, 1)
    return None


def starter_exercises(db: Session, codes: list[str], profile) -> tuple[list[dict], list[str]]:
    """The exercises, and a line per provisional profile rule that changed
    them. Empty when the grid allows nothing (a refer condition)."""
    approved = ctx.approved_exercises(db, codes)
    ranks = _usefulness(db, codes)
    by_type = {e.activity_type: e for e in db.scalars(select(Exercise))}
    rules: list[str] = []
    older, bmi = profile.age >= OLDER_AGE, _bmi(profile)
    if older or (bmi is not None and bmi >= HIGH_BMI):
        dropped = [e["display_name"] for e in approved if e["activity_type"] in HIGH_IMPACT]
        approved = [e for e in approved if e["activity_type"] not in HIGH_IMPACT]
        if dropped:
            why = f"age {profile.age} >= {OLDER_AGE}" if older else f"BMI {bmi} >= {HIGH_BMI:g}"
            rules.append(f"{', '.join(dropped)} left out: {why} (provisional rule)")
    # "safe" before "modify": a starter plan stays moderate, so a modified
    # exercise only makes the cut when there aren't enough safe ones.
    approved.sort(key=lambda e: (e["verdict"] == "modify", ranks.get(e["activity_type"], 99),
                                 by_type[e["activity_type"]].priority_order))
    count = EXERCISES_BY_EXPERIENCE.get(profile.experience, EXERCISES_BY_EXPERIENCE["beginner"])
    exercises = []
    for e in approved[:count]:
        amount, step = e["default_amount"], by_type[e["activity_type"]].progression_step
        if older and amount - step >= step - 1e-9:
            amount = round(amount - step, 2)
        exercises.append({"activity_type": e["activity_type"], "name": e["display_name"], "unit": e["unit"],
                          "sets": e["default_sets"], "amount": amount, "notes": " ".join(e["notes"])})
    if older and exercises:
        rules.append(f"Doses one step below the defaults: age {profile.age} >= {OLDER_AGE} (provisional rule)")
    return exercises, rules


def easier_exercises(db: Session, current: list[dict], targets: set[str]) -> tuple[list[dict], list[dict]]:
    """One step down for each targeted exercise (all of them if `targets` is
    empty): the amount drops by its progression step, or, once the amount is
    at one step, a set goes. An exercise already at 1 set of one step stays
    as it is and is marked for the doctor."""
    steps = {e.activity_type: e.progression_step for e in db.scalars(select(Exercise))}
    exercises, changes = [], []
    for e in current:
        e = dict(e)
        if targets and e["activity_type"] not in targets:
            exercises.append(e)
            continue
        step = steps.get(e["activity_type"], 1)
        before = {"sets": e["sets"], "amount": e["amount"]}
        if e["amount"] - step >= step - 1e-9:
            e["amount"] = round(e["amount"] - step, 2)
            note = f"{before['amount']:g} -> {e['amount']:g} {e['unit']} per set"
        elif e["sets"] > 1:
            e["sets"] -= 1
            note = f"{before['sets']} -> {e['sets']} sets"
        else:
            note = "Already at the lowest dose; needs the doctor's decision"
        exercises.append(e)
        changes.append({"activity_type": e["activity_type"], "name": e["name"], "from": before,
                        "to": {"sets": e["sets"], "amount": e["amount"]}, "note": note})
    return exercises, changes


def on_profile_saved(db: Session, user: User, old_codes: list[str]) -> PlanProposal | None:
    """A patient without a plan gets a starter draft; one whose conditions
    changed gets an updated draft. Either way it waits for the doctor."""
    plan = latest_plan(db, user.id)
    if plan is None:
        return _refresh_starter(db, user)
    if set(old_codes) != set(ctx.condition_codes(user)):
        return _redraft_for_conditions(db, user, plan, old_codes)
    return None


def latest_plan(db: Session, user_id: str) -> DoctorPlan | None:
    return db.scalars(select(DoctorPlan).where(DoctorPlan.user_id == user_id)
                      .order_by(DoctorPlan.created_at.desc()).limit(1)).first()


def _conditions(db: Session, codes: list[str]) -> list[Condition]:
    return db.scalars(select(Condition).where(Condition.code.in_(codes)).order_by(Condition.display_order)).all()


def _replace_pending(db: Session, user: User, proposal: PlanProposal) -> PlanProposal:
    """Swap in a fresh draft, unless the pending one already says the same."""
    pending = pending_proposal(db, user.id)
    if pending is not None:
        if (pending.kind, pending.source, pending.exercises) == (proposal.kind, proposal.source, proposal.exercises):
            return pending
        pending.status = "superseded"
    db.add(proposal)
    db.flush()
    return proposal


def _needs_doctor(conditions: list[Condition]) -> str:
    refer = [c.display_name for c in conditions if c.bucket == "refer"]
    return ("Needs a doctor-written plan: " + (", ".join(refer) if refer else "no exercise is approved for "
            "every condition") + ". The rules can't draft one.")


def _refresh_starter(db: Session, user: User) -> PlanProposal:
    pending = pending_proposal(db, user.id)
    if pending is not None and pending.kind != "starter":
        return pending
    codes = ctx.condition_codes(user)
    conditions = _conditions(db, codes)
    names = ", ".join(c.display_name for c in conditions)
    exercises, rules = starter_exercises(db, codes, user.profile)
    if exercises:
        source, instructions = "rules", f"Starter plan built from the safety rules for: {names}."
        reason = "\n".join([f"New patient. Exercises chosen by the safety grid for: {names}.", *rules])
    else:
        source, instructions, reason = "doctor", "", _needs_doctor(conditions)
    return _replace_pending(db, user, PlanProposal(user_id=user.id, kind="starter", source=source,
                                                   instructions=instructions, exercises=exercises,
                                                   changes=[], reason=reason))


def _blocked_by(db: Session, activity_type: str, codes: list[str]) -> list[str]:
    """The conditions among `codes` that rule an exercise out: "avoid", or no
    rule at all (the grid fails closed)."""
    verdicts = dict(db.execute(select(SafetyRule.condition_code, SafetyRule.verdict)
                               .where(SafetyRule.activity_type == activity_type,
                                      SafetyRule.condition_code.in_(codes))).all())
    return [c for c in codes if verdicts.get(c, "avoid") == "avoid"]


def _redraft_for_conditions(db: Session, user: User, plan: DoctorPlan,
                            old_codes: list[str]) -> PlanProposal | None:
    codes = ctx.condition_codes(user)
    conditions = _conditions(db, codes)
    names = {c.code: c.display_name for c in _conditions(db, list(set(codes) | set(old_codes)))}
    added = [c for c in codes if c not in old_codes]
    removed = [c for c in old_codes if c not in codes]
    what = "; ".join(filter(None, ["added " + ", ".join(names[c] for c in added) if added else "",
                                   "removed " + ", ".join(names[c] for c in removed) if removed else ""]))
    reason = f"Conditions changed ({what})."
    # Build on a pending easier/update draft so the patient's earlier request isn't lost.
    pending = pending_proposal(db, user.id)
    base = pending.exercises if pending is not None and pending.kind in ("easier", "update") else plan.exercises

    if any(c.bucket == "refer" for c in conditions):
        return _replace_pending(db, user, PlanProposal(
            user_id=user.id, kind="update", source="doctor", instructions="", exercises=[], changes=[],
            reason=f"{reason} {_needs_doctor(conditions)} The current plan stays until you replace it.",
            based_on_plan_id=plan.id))

    # Only a newly added condition can rule out an exercise the doctor already
    # chose; exercises the doctor prescribed against the grid stay their call.
    approved = {e["activity_type"]: e for e in ctx.approved_exercises(db, codes)}
    exercises, changes = [], []
    for e in base:
        blocked = _blocked_by(db, e["activity_type"], added)
        if blocked:
            changes.append({"activity_type": e["activity_type"], "name": e["name"],
                            "from": {"sets": e["sets"], "amount": e["amount"]}, "to": None,
                            "note": "Removed: not safe with " + ", ".join(names[c] for c in blocked)})
            continue
        e = dict(e)
        if e["activity_type"] in approved:
            e["notes"] = " ".join(approved[e["activity_type"]]["notes"]) or e["notes"]
        exercises.append(e)
    picks, rules = starter_exercises(db, codes, user.profile)
    for e in picks:
        if len(exercises) >= len(base):
            break
        if e["activity_type"] not in {x["activity_type"] for x in exercises}:
            exercises.append(e)
            changes.append({"activity_type": e["activity_type"], "name": e["name"], "from": None,
                            "to": {"sets": e["sets"], "amount": e["amount"]},
                            "note": "Added in place of a removed exercise"})
    if not changes:
        return None  # nothing in the plan is affected
    return _replace_pending(db, user, PlanProposal(
        user_id=user.id, kind="update", source="rules", exercises=exercises, changes=changes,
        instructions=f"Your plan, updated for your conditions.\n{plan.instructions}",
        reason="\n".join([reason, *rules]), based_on_plan_id=plan.id))


def request_easier(db: Session, user: User, plan: DoctorPlan, targets: list[str],
                   note: str | None) -> PlanProposal:
    exercises, changes = easier_exercises(db, plan.exercises, set(targets))
    which = ", ".join(c["name"] for c in changes)
    proposal = PlanProposal(
        user_id=user.id, kind="easier", source="rules", exercises=exercises, changes=changes,
        instructions=f"An easier version of your plan from {plan.created_at.date().isoformat()}.\n"
                     f"{plan.instructions}",
        reason=f"Patient said the plan is too hard ({'all exercises' if not targets else which}). "
               "Each one dropped a step.",
        patient_note=note, based_on_plan_id=plan.id)
    db.add(proposal)
    db.flush()
    return proposal


def escalate_painful_plan(db: Session, user: User, plan: DoctorPlan, targets: list[str], pain: int,
                          note: str | None):
    which = ", ".join(e["name"] for e in plan.exercises if not targets or e["activity_type"] in targets)
    summary = (f"Patient says their plan from {plan.created_at.date().isoformat()} is too hard, with pain "
               f"{pain}/10 ({which})." + (f' Patient wrote: "{note[:600]}".' if note else ""))
    return upsert_case(db, user, "priority", f"Plan too hard with pain {pain}/10", summary,
                       ["plan_too_hard", "pain_reported_high"])


def plan_message(doctor_name: str, instructions: str, exercises: list[dict]) -> str:
    lines = [f"Plan from Dr. {doctor_name}:", instructions]
    lines += [f"- {e['name']}: {e['sets']} x {e['amount']:g} {e['unit']}" + (f" ({e['notes']})" if e["notes"] else "")
              for e in exercises]
    return "\n".join(lines)


def give_plan(db: Session, doctor: User, user_id: str, instructions: str, exercises: list[dict],
              case_id: str | None = None) -> DoctorPlan:
    """The only way a plan reaches a patient. It also lands in their chat, so
    they see it and the agent has it in its history from then on."""
    plan = DoctorPlan(case_id=case_id, user_id=user_id, doctor_id=doctor.id,
                      instructions=instructions, exercises=exercises)
    db.add(plan)
    db.add(ChatMessage(user_id=user_id, role="doctor", content=plan_message(doctor.name, instructions, exercises),
                       case_id=case_id))
    db.flush()
    return plan


def approve(db: Session, proposal: PlanProposal, doctor: User, instructions: str,
            exercises: list[dict], review_note: str | None) -> DoctorPlan:
    plan = give_plan(db, doctor, proposal.user_id, instructions, exercises)
    proposal.status = "approved"
    proposal.approved_plan_id = plan.id
    _reviewed(proposal, doctor, review_note)
    return plan


def reject(proposal: PlanProposal, doctor: User, review_note: str) -> None:
    proposal.status = "rejected"
    _reviewed(proposal, doctor, review_note)


def _reviewed(proposal: PlanProposal, doctor: User, review_note: str | None) -> None:
    proposal.reviewed_by = doctor.id
    proposal.review_note = review_note
    proposal.reviewed_at = datetime.now(timezone.utc)


def proposal_dict(p: PlanProposal) -> dict:
    return {"id": p.id, "kind": p.kind, "source": p.source, "status": p.status,
            "created_at": p.created_at.isoformat()}
