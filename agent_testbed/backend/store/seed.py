"""Create the agent_tmp schema and tables, and rebuild the reference data on
every start: our data/*.csv merged with the reference DB (store.reference).

Merge rules (BUILD_PLAN.md, "How the reference data merges"):
- A condition, exercise or rule found in either source is kept.
- Where both have a rule or a condition bucket, the stricter one wins
  (avoid > modify > safe, refer > supported). Every disagreement is logged.
- Doses come from our CSV; instructions and images from the reference DB.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from sqlalchemy import text

from store import reference
from store.db import SCHEMA, Base, engine, session
from store.models import Condition, ConditionAlias, Exercise, SafetyRule, WarningComplaint

log = logging.getLogger("store.seed")

DATA = Path(__file__).resolve().parent.parent / "data"
VERDICT_RANK = {"safe": 0, "modify": 1, "avoid": 2}
BUCKET_RANK = {"supported": 0, "refer": 1}
_DOSE_FIELDS = ("amount_unit", "default_sets", "default_amount", "max_sets", "max_amount")


def _rows(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _int(value, default=None):
    return int(value) if value not in (None, "") else default


def _float(value, default=None):
    return float(value) if value not in (None, "") else default


# Columns added to tables we keep, for databases created before them. Safe to
# run on every start.
ADDED_COLUMNS = (
    f'ALTER TABLE "{SCHEMA}".plan_proposals ADD COLUMN IF NOT EXISTS assessment_id VARCHAR(36) '
    f'REFERENCES "{SCHEMA}".assessments (id)',
)


def init_store() -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    # Reference tables are rebuilt from their sources, so their columns follow the models.
    for model in (SafetyRule, ConditionAlias, WarningComplaint, Exercise, Condition):
        model.__table__.drop(engine, checkfirst=True)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # create_all doesn't add columns to tables that already exist.
        for statement in ADDED_COLUMNS:
            conn.execute(text(statement))
        # Keep the tables out of Supabase's public Data API.
        for table in Base.metadata.sorted_tables:
            conn.execute(text(f'ALTER TABLE "{SCHEMA}"."{table.name}" ENABLE ROW LEVEL SECURITY'))
    conditions, exercises, rules = _merged()
    aliases = _aliases(conditions)
    with session() as db:
        db.add_all(Condition(**c) for c in conditions.values())
        db.add_all(Exercise(**e) for e in exercises.values())
        db.flush()
        db.add_all(SafetyRule(**r) for r in rules.values())
        db.add_all(ConditionAlias(**a) for a in aliases)
        db.add_all(WarningComplaint(phrase=r["phrase"].strip().lower(), label=r["label"])
                   for r in _rows("warning_complaints.csv"))


# Not condition codes: the safety rules decide controlled or not (agent/conditions.py).
ALIAS_MARKERS = {"bp_any", "diabetes_any"}


def _aliases(conditions: dict) -> list[dict]:
    """data/condition_aliases.csv, minus rows pointing at an unknown code."""
    out = []
    for r in _rows("condition_aliases.csv"):
        if r["code"] not in conditions and r["code"] not in ALIAS_MARKERS:
            log.warning("Alias %r -> %r dropped: unknown condition code", r["phrase"], r["code"])
            continue
        out.append({"source": r["source"], "phrase": r["phrase"].strip(), "code": r["code"], "note": r["note"] or ""})
    log.info("Condition aliases loaded: %d", len(out))
    return out


def _from_csv() -> tuple[dict, dict, dict]:
    conditions = {r["condition_code"]: {
        "code": r["condition_code"], "display_name": r["display_name"], "bucket": r["bucket"],
        "display_order": _int(r["display_order"], 0), "notes": r.get("notes") or ""}
        for r in _rows("conditions.csv")}
    exercises = {r["activity_type"]: {
        "activity_type": r["activity_type"], "display_name": r["display_name"],
        "prescription_type": r["prescription_type"], "amount_unit": r["amount_unit"],
        "default_sets": _int(r["default_sets"], 1), "default_amount": _float(r["default_amount"], 1),
        "max_sets": _int(r["max_sets"], 1), "max_amount": _float(r["max_amount"], 1),
        "per_side": r["per_side"].strip().lower() == "true", "rest_seconds": _int(r["rest_seconds"]),
        "progression_step": _float(r["progression_step"], 1), "priority_order": _int(r["priority_order"], 0),
        "instructions": [], "images": []}
        for r in _rows("activity_taxonomy.csv")}
    rules = {(r["condition_code"], r["activity_type"]): {
        "condition_code": r["condition_code"], "activity_type": r["activity_type"], "verdict": r["verdict"],
        "note": r["note"], "usefulness_rank": _int(r["usefulness_rank"])}
        for r in _rows("safety_grid.csv")}
    return conditions, exercises, rules


def _merged() -> tuple[dict, dict, dict]:
    conditions, exercises, rules = _from_csv()
    ref = reference.fetch()
    disagreements: list[str] = []
    if ref:
        for r in ref["conditions"]:
            c = conditions.get(r["condition_code"])
            if c is None:
                conditions[r["condition_code"]] = {
                    "code": r["condition_code"], "display_name": r["display_name"], "bucket": r["bucket"],
                    "display_order": r["display_order"] or 0, "notes": r["notes"]}
                continue
            if r["bucket"] != c["bucket"]:
                disagreements.append(f"condition {c['code']}: csv {c['bucket']}, reference {r['bucket']}")
                if BUCKET_RANK.get(r["bucket"], 1) > BUCKET_RANK.get(c["bucket"], 1):
                    c["bucket"] = r["bucket"]
            c["notes"] = c["notes"] or r["notes"]

        for r in ref["exercises"]:
            media = {"instructions": [s.strip() for s in r["instructions"] if s and s.strip()],
                     "images": [u for u in r["images"] if u]}
            e = exercises.get(r["activity_type"])
            if e is None:
                exercises[r["activity_type"]] = {
                    **{k: r[k] for k in ("activity_type", "display_name", "prescription_type", "amount_unit",
                                         "default_sets", "default_amount", "max_sets", "max_amount",
                                         "rest_seconds", "progression_step")},
                    "per_side": bool(r["per_side"]), "priority_order": r["priority_order"] or 0, **media}
                continue
            for field in _DOSE_FIELDS:
                if r[field] is not None and r[field] != e[field]:
                    disagreements.append(f"exercise {e['activity_type']} {field}: csv {e[field]} (kept), "
                                         f"reference {r[field]}")
            e.update(media)

        for r in ref["rules"]:
            key = (r["condition_code"], r["activity_type"])
            mine = rules.get(key)
            if mine is None:
                rules[key] = {**r, "usefulness_rank": None}
                continue
            if r["verdict"] != mine["verdict"]:
                disagreements.append(f"rule {key[0]} x {key[1]}: csv {mine['verdict']}, reference {r['verdict']}")
                if VERDICT_RANK.get(r["verdict"], 2) > VERDICT_RANK.get(mine["verdict"], 2):
                    mine["verdict"], mine["note"] = r["verdict"], r["note"]

    # A rule must point at a known condition and exercise.
    orphans = [k for k in rules if k[0] not in conditions or k[1] not in exercises]
    for key in orphans:
        disagreements.append(f"rule {key[0]} x {key[1]} dropped: unknown condition or exercise")
        del rules[key]

    log.info("Reference data: %d conditions, %d exercises (%d with instructions), %d rules; source: %s",
             len(conditions), len(exercises), sum(1 for e in exercises.values() if e["instructions"]), len(rules),
             "data/*.csv + reference DB" if ref else "data/*.csv only")
    for line in disagreements:
        log.warning("Reference data disagreement: %s", line)
    return conditions, exercises, rules
