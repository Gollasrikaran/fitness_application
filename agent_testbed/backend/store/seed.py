"""Create the agent_tmp schema and tables, and rebuild the reference data on
every start: our data/*.csv merged with the reference DB (store.reference).

Merge rules (BUILD_PLAN.md, "How the reference data merges"):
- A condition, exercise or rule found in either source is kept.
- Where both have a rule or a condition bucket, the stricter one wins
  (avoid > modify > safe, refer > supported). Every disagreement is logged.
- Doses come from our CSV; instructions and images from the reference DB,
  or our CSV's instructions for exercises the reference DB has no steps for.
"""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from sqlalchemy import text

from store import reference
from store.db import SCHEMA, Base, engine, session
from store.models import Condition, ConditionAlias, Exercise, ReadingRule, SafetyRule, WarningComplaint

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
    f'ALTER TABLE "{SCHEMA}".assessments ADD COLUMN IF NOT EXISTS readings JSON',
)


def init_store() -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    # Reference tables are rebuilt from their sources, so their columns follow the models.
    for model in (SafetyRule, ReadingRule, ConditionAlias, WarningComplaint, Exercise, Condition):
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
        db.add_all(ReadingRule(**r) for r in reading_rules())


# Allowed values of the exercise properties the reading rules select on.
EXERCISE_PROPERTIES = {
    "exercise_type": {"aerobic", "strength", "isometric", "mobility", "stretch", "breathing", "balance"},
    "intensity": {"light", "moderate", "vigorous"},
    "position": {"standing", "chair", "floor"},
    "impact": {"low", "high"},
}


# The readings the rules can test, and the fields of each (store.plans.latest_readings).
READING_FIELDS = {"bp": {"sys", "dia"}, "sugar": {"high", "low"}, "hb": {"value"}, "spo2": {"value"},
                  "pulse": {"value"}}
_TERM = re.compile(r"^\s*([a-z]+)\s*(>=|<=|>|<)\s*(\d+(?:\.\d+)?)\s*$")


def parse_when(when: str, metric: str) -> list[list]:
    """"sys>=140 or dia>=90" -> [["sys", ">=", 140.0], ["dia", ">=", 90.0]]
    (any one term applies). ValueError for anything else."""
    terms = []
    for part in when.split(" or "):
        m = _TERM.match(part)
        if not m or m[1] not in READING_FIELDS.get(metric, ()):
            raise ValueError(f"bad term {part!r} for {metric}")
        terms.append([m[1], m[2], float(m[3])])
    return terms


def reading_rules() -> list[dict]:
    """data/reading_rules.csv, minus rows with an unknown reading, property
    or action, or a condition that can't be read."""
    out = []
    for r in _rows("reading_rules.csv"):
        try:
            if r["metric"] not in READING_FIELDS or r["field"] not in EXERCISE_PROPERTIES \
                    or r["action"] not in ("block", "allow_only"):
                raise ValueError("unknown metric, field or action")
            terms = parse_when(r["when"], r["metric"])
        except ValueError as exc:
            log.warning("Reading rule %r dropped: %s", r, exc)
            continue
        out.append({"metric": r["metric"], "band": r["band"], "when": r["when"], "terms": terms,
                    "action": r["action"], "field": r["field"],
                    "values": [v.strip() for v in r["values"].split("|") if v.strip()], "note": r["note"]})
    log.info("Reading rules loaded: %d", len(out))
    return out


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
        # Steps separated by "|"; used when the reference DB has none for this exercise.
        "instructions": [s.strip() for s in (r.get("instructions") or "").split("|") if s.strip()], "images": [],
        **{k: (r.get(k) or "").strip() for k in EXERCISE_PROPERTIES},
        "breath_hold": (r.get("breath_hold") or "").strip().lower() == "true"}
        for r in _rows("activity_taxonomy.csv")}
    for e in exercises.values():
        for k, allowed in EXERCISE_PROPERTIES.items():
            if e[k] not in allowed:
                log.warning("Exercise %s: %s %r is not one of %s", e["activity_type"], k, e[k], sorted(allowed))
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
            e.update({k: v for k, v in media.items() if v})  # the reference DB's steps and images win when it has them

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
