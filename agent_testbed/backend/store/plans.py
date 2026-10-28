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
- violations(): why a draft breaks the rules. Every AI or rules draft is
  checked before it is saved, and one that breaks them is never saved.
- Doctor edits are different: the doctor has the final say. The grid never
  blocks them; doctor_warnings() shows a small warning instead.
- reading_limits(): what the patient's latest BP reading rules out
  (data/reading_rules.csv, by exercise property). Applied like the grid: AI
  and rules drafts never hold a ruled-out exercise; the doctor gets a warning.

Plans never get harder on their own. A "refer" condition allows no exercise:
the doctor writes the plan.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from store.models import Assessment, Condition, Exercise, Plan, PlanProposal, ReadingRule, SafetyRule

EXERCISES_BY_EXPERIENCE = {"beginner": 4, "intermediate": 5, "active": 7}
# The clinic record doesn't say how active someone is: start everyone as a
# beginner (the most moderate plan). The doctor can add more.
DEFAULT_EXPERIENCE = "beginner"

# PROVISIONAL thresholds so we can build; the doctor confirms or replaces them.
OLDER_AGE = 60         # at or above: high-impact exercises left out, doses one step lower
HIGH_BMI = 30.0        # at or above: high-impact exercises left out
HIGH_IMPACT = {"running"}
MAX_EXERCISES = 5      # in any draft the agent makes

# Which BP reading counts (decided 2026-10-28): the latest, if within this
# many days. A patient with BP and no recent reading is treated as 140/90.
BP_READING_DAYS = 90
BP_CODES = {"bp_controlled", "high_bp", "bp_any"}
ASSUMED_BP = {"sys": 140.0, "dia": 90.0, "date": None, "assumed": True}


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


def _num(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def dose_text(sets: int, amount: float, unit: str, kind: str | None, per_side: bool) -> str:
    """The dose in plain words for the patient, e.g. "2 sets × 5 repetitions,
    each side", "2 sets × hold 10 seconds", "1 km", "5 minutes"."""
    if kind == "reps" or unit == "count":
        each = f"{_num(amount)} repetitions"
    elif kind == "hold" or unit == "sec":
        each = f"hold {_num(amount)} seconds"
    elif unit == "min":
        each = f"{_num(amount)} minutes"
    else:
        each = f"{_num(amount)} {unit}"
    text = each if kind in ("distance", "time") and sets == 1 else f"{sets} sets × {each}"
    return text + (", each side" if per_side else "")


def patient_plan(db: Session, p: Plan | None, doctor_name: str | None) -> dict | None:
    """What the patient sees: the approved doses, with each exercise's fixed
    details (rest, each side, steps) from the exercise table. Nothing about
    drafts, conditions or the assessment."""
    if p is None:
        return None
    by_type = {e.activity_type: e for e in db.scalars(select(Exercise))}
    exercises = []
    for x in p.exercises:
        ex = by_type.get(x.get("activity_type"))
        per_side = bool(ex and ex.per_side)
        rest = ex.rest_seconds if ex and ex.rest_seconds and x["sets"] > 1 else None
        exercises.append({"name": x.get("name") or (ex.display_name if ex else x.get("activity_type")),
                          "dose": dose_text(x["sets"], x["amount"], x.get("unit") or (ex.amount_unit if ex else ""),
                                            ex.prescription_type if ex else None, per_side),
                          "rest_seconds": rest, "steps": list(ex.instructions) if ex else [],
                          "notes": x.get("notes") or ""})
    return {"doctor_name": doctor_name, "given_on": p.created_at.date().isoformat(),
            "instructions": p.instructions, "exercises": exercises}


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
               bmi: float | None, bp: dict | None = None) -> tuple[list[dict], list[str]]:
    """Every exercise allowed for this patient, most suitable first, at its
    starting dose; and a line per provisional profile rule that changed them.
    Entries: {activity_type, name, unit, sets, amount, notes, verdict}."""
    approved = approved_exercises(db, codes)
    blocked, bp_lines = reading_limits(db, codes, bp)
    names = {e["activity_type"]: e["display_name"] for e in approved}
    rules: list[str] = []
    for why in bp_lines:  # say what each BP rule took out of this patient's list
        out_now = [names[k] for k, w in blocked.items() if w == why and k in names]
        if out_now:
            rules.append(f"{why} Left out: {', '.join(out_now)}.")
    approved = [e for e in approved if e["activity_type"] not in blocked]
    ranks = _usefulness(db, codes)
    by_type = {e.activity_type: e for e in db.scalars(select(Exercise))}
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
                      experience: str = DEFAULT_EXPERIENCE, bp: dict | None = None) -> tuple[list[dict], list[str]]:
    """The rule-built plan (no AI), and a line per provisional profile rule
    that changed it."""
    allowed, rules = candidates(db, codes, age, bmi, bp)
    count = EXERCISES_BY_EXPERIENCE.get(experience, EXERCISES_BY_EXPERIENCE["beginner"])
    return [plan_entry(e) for e in allowed[:count]], rules


def violations(db: Session, exercises: list[dict], codes: list[str], bp: dict | None = None) -> list[str]:
    """Why a draft breaks the safety rules; empty when it doesn't. Fails
    closed: an unknown exercise or condition, a missing rule, "avoid" for any
    condition, a "refer" condition, a dose outside 1..max, or an exercise
    the patient's BP reading rules out is a violation."""
    problems = []
    blocked, _ = reading_limits(db, codes, bp)
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
        if kind in blocked:
            problems.append(f"{ex.display_name}: {blocked[kind]}")
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


# ── Rules by reading (BP) ───────────────────────────────────────────────────

def _reading(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def latest_bp(vitals: list[dict], today: date) -> dict | None:
    """The newest BP reading in the visits (newest first), if taken in the
    last BP_READING_DAYS days: {"sys", "dia", "date"}."""
    for v in vitals:
        sys_, dia = _reading(v.get("bp_sys")), _reading(v.get("bp_dia"))
        if sys_ is None or dia is None:
            m = re.match(r"\s*(\d{2,3})\s*/\s*(\d{2,3})", str(v.get("bp") or ""))
            sys_, dia = (float(m[1]), float(m[2])) if m else (None, None)
        if sys_ and dia and v.get("date"):
            day = date.fromisoformat(str(v["date"])[:10])
            return {"sys": sys_, "dia": dia, "date": day.isoformat()} if (today - day).days <= BP_READING_DAYS else None
    return None


def reading_limits(db: Session, codes: list[str], bp: dict | None) -> tuple[dict[str, str], list[str]]:
    """What the patient's BP rules out: ({activity_type: why}, a line per rule
    that applies). Rules add up (a higher band also gets the lower bands').
    No recent reading: nothing, unless the patient has BP, then 140/90."""
    if bp is None:
        if not set(codes) & BP_CODES:
            return {}, []
        bp = ASSUMED_BP
    reading = (f"{bp['sys']:g}/{bp['dia']:g} (no reading in the last {BP_READING_DAYS} days, so treated as this)"
               if bp.get("assumed") else f"{bp['sys']:g}/{bp['dia']:g} on {bp['date']}")
    exercises = list(db.scalars(select(Exercise)))
    blocked: dict[str, str] = {}
    lines = []
    for r in db.scalars(select(ReadingRule).where(ReadingRule.metric == "bp").order_by(ReadingRule.id)):
        if bp["sys"] < r.sys_from and bp["dia"] < r.dia_from:
            continue
        why = r.note.format(reading=reading)
        lines.append(why)
        for e in exercises:
            if (getattr(e, r.field) in r.values) == (r.action == "block"):
                blocked.setdefault(e.activity_type, why)
    return blocked, lines


# ── Doctor edits: the doctor has the final say ──────────────────────────────

def _verdicts(db: Session, codes: list[str]) -> dict[str, dict[str, SafetyRule]]:
    rules: dict[str, dict[str, SafetyRule]] = defaultdict(dict)
    for r in db.scalars(select(SafetyRule).where(SafetyRule.condition_code.in_(codes))):
        rules[r.activity_type][r.condition_code] = r
    return rules


def exercise_catalog(db: Session, codes: list[str], bp: dict | None = None) -> list[dict]:
    """Every exercise, for the doctor's picker, with what the grid says for
    this patient: the strictest across the conditions ("avoid", "unreviewed"
    when a condition has no rule for it, "modify", "safe"), or "not advised"
    when the patient's BP reading rules it out."""
    rules = _verdicts(db, codes)
    blocked, _ = reading_limits(db, codes, bp)
    out = []
    for ex in db.scalars(select(Exercise).order_by(Exercise.priority_order)):
        by_condition = rules.get(ex.activity_type, {})
        verdicts = {r.verdict for r in by_condition.values()}
        verdict = ("avoid" if "avoid" in verdicts else "unreviewed" if not codes or set(codes) - set(by_condition)
                   else "modify" if "modify" in verdicts else "safe")
        notes = dict.fromkeys(r.note for r in by_condition.values() if r.verdict != "safe" and r.note)
        if ex.activity_type in blocked and verdict != "avoid":
            verdict, notes = "not advised", {blocked[ex.activity_type]: None, **notes}
        out.append({"activity_type": ex.activity_type, "name": ex.display_name, "unit": ex.amount_unit,
                    "default_sets": ex.default_sets, "default_amount": ex.default_amount, "max_sets": ex.max_sets,
                    "max_amount": ex.max_amount, "per_side": ex.per_side, "verdict": verdict,
                    "notes": " ".join(notes)})
    return out


def doctor_exercises(db: Session, items: list[dict]) -> list[dict]:
    """The doctor's exercises as stored in a plan. Only input errors are
    refused (ValueError): an unknown exercise, one listed twice, or a dose
    that isn't a positive number. The grid never blocks a doctor."""
    by_type = {e.activity_type: e for e in db.scalars(select(Exercise))}
    out, seen = [], set()
    for x in items:
        ex = by_type.get(x.get("activity_type"))
        if ex is None:
            raise ValueError(f"Unknown exercise: {x.get('activity_type')}")
        if ex.activity_type in seen:
            raise ValueError(f"{ex.display_name} is listed twice")
        seen.add(ex.activity_type)
        sets, amount = x.get("sets"), x.get("amount")
        if isinstance(sets, bool) or not isinstance(sets, int) or sets < 1:
            raise ValueError(f"{ex.display_name}: sets must be a whole number, at least 1")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
            raise ValueError(f"{ex.display_name}: the amount must be more than 0")
        out.append({"activity_type": ex.activity_type, "name": ex.display_name, "unit": ex.amount_unit,
                    "sets": sets, "amount": float(amount), "notes": (x.get("notes") or "").strip()})
    return out


def doctor_warnings(db: Session, exercises: list[dict], codes: list[str],
                    bp: dict | None = None) -> dict[str, list[str]]:
    """Small warnings for the doctor, per exercise: marked avoid or not
    reviewed for one of the patient's conditions, ruled out by the patient's
    BP reading, or a dose above the usual maximum. Never blocks."""
    names = condition_names(db, codes)
    blocked, _ = reading_limits(db, codes, bp)
    rules = _verdicts(db, codes)
    by_type = {e.activity_type: e for e in db.scalars(select(Exercise))}
    out = {}
    for x in exercises:
        ex = by_type.get(x.get("activity_type"))
        if ex is None:
            continue
        warn = []
        for code in codes:
            rule = rules.get(ex.activity_type, {}).get(code)
            if rule is None:
                warn.append(f"Not reviewed for {names.get(code, code)}")
            elif rule.verdict == "avoid":
                warn.append(f"Marked avoid for {names.get(code, code)}" + (f": {rule.note}" if rule.note else ""))
        if ex.activity_type in blocked:
            warn.append(f"Not advised: {blocked[ex.activity_type]}")
        sets, amount = x.get("sets"), x.get("amount")
        if isinstance(sets, (int, float)) and sets > ex.max_sets:
            warn.append(f"{sets} sets is above the usual maximum of {ex.max_sets}")
        if isinstance(amount, (int, float)) and amount > ex.max_amount:
            warn.append(f"{amount:g} {ex.amount_unit} is above the usual maximum of {ex.max_amount:g}")
        if warn:
            out[ex.activity_type] = warn
    return out


def review_queue(db: Session, doctor_id: str) -> list[dict]:
    """Drafts waiting for review that this doctor generated, oldest first."""
    rows = db.execute(select(PlanProposal, Assessment)
                      .join(Assessment, PlanProposal.assessment_id == Assessment.id)
                      .where(PlanProposal.status == "pending", Assessment.doctor_id == doctor_id)
                      .order_by(PlanProposal.created_at)).all()
    return [{"proposal_id": p.id, "patient_id": p.patient_id, "kind": p.kind, "source": p.source,
             "severity": a.severity, "problem": a.problem, "requested_at": p.created_at.isoformat(timespec="minutes")}
            for p, a in rows]


def exercise_changes(old: list[dict], new: list[dict]) -> list[dict]:
    """What changed between two exercise lists: an update to the current
    plan, or the doctor's edit of a draft."""
    before = {e["activity_type"]: e for e in old}
    after = {e["activity_type"]: e for e in new}
    out = []
    for kind, e in before.items():
        if kind not in after:
            out.append({"activity_type": kind, "name": e["name"], "from": {"sets": e["sets"], "amount": e["amount"]},
                        "to": None, "note": "Removed"})
    for kind, e in after.items():
        was = before.get(kind)
        dose = {"sets": e["sets"], "amount": e["amount"]}
        if was is None:
            out.append({"activity_type": kind, "name": e["name"], "from": None, "to": dose, "note": "Added"})
        elif (was["sets"], was["amount"]) != (e["sets"], e["amount"]):
            out.append({"activity_type": kind, "name": e["name"], "from": {"sets": was["sets"], "amount": was["amount"]},
                        "to": dose, "note": "Dose changed"})
    return out


def review_summary(db: Session, doctor_id: str | None = None) -> dict:
    """How doctors handled the drafts (phase 8): approved as drafted, approved
    with edits, or rejected, and what they changed. Drafts a doctor had to
    write (source "doctor") are counted on their own: there was nothing to edit."""
    q = select(PlanProposal, Plan).outerjoin(Plan, PlanProposal.approved_plan_id == Plan.id).where(
        PlanProposal.status.in_(("approved", "rejected")))
    if doctor_id:
        q = q.where(PlanProposal.reviewed_by == doctor_id)
    by_source: dict[str, dict] = defaultdict(lambda: {"reviewed": 0, "approved_as_drafted": 0,
                                                       "approved_with_edits": 0, "rejected": 0})
    edits = {"Added": defaultdict(int), "Removed": defaultdict(int), "Dose changed": defaultdict(int)}
    dose_up = dose_down = instructions_changed = 0
    rejections, written = [], 0
    for p, plan in db.execute(q.order_by(PlanProposal.reviewed_at)).all():
        if p.source == "doctor":
            written += p.status == "approved"
            if p.status == "rejected":
                rejections.append({"source": p.source, "note": p.review_note or ""})
            continue
        s = by_source[p.source]
        s["reviewed"] += 1
        if p.status == "rejected":
            s["rejected"] += 1
            rejections.append({"source": p.source, "note": p.review_note or ""})
            continue
        changes = exercise_changes(p.exercises, plan.exercises)
        new_text = (plan.instructions or "").strip() != (p.instructions or "").strip()
        s["approved_with_edits" if changes or new_text else "approved_as_drafted"] += 1
        instructions_changed += new_text
        for c in changes:
            edits[c["note"]][c["name"]] += 1
            if c["note"] == "Dose changed":
                bigger = c["to"]["sets"] * c["to"]["amount"] > c["from"]["sets"] * c["from"]["amount"]
                dose_up += bigger
                dose_down += not bigger
    top = lambda counts: sorted(({"name": k, "times": v} for k, v in counts.items()), key=lambda x: -x["times"])
    return {"by_source": dict(by_source), "doctor_written_approved": written,
            "added": top(edits["Added"]), "removed": top(edits["Removed"]), "dose_changed": top(edits["Dose changed"]),
            "dose_raised": dose_up, "dose_lowered": dose_down, "instructions_changed": instructions_changed,
            "rejections": rejections}


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
