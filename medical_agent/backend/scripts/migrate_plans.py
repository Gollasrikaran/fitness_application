"""Bring an existing database up to date for rule-drafted plans. Safe to re-run.

    python scripts/migrate_plans.py

- exercises:      + progression_step, priority_order
- safety_rules:   + usefulness_rank
- doctor_plans:   case_id may be empty (plans approved outside a case)
- plan_proposals: new table
then fills the new columns from the CSVs in place (rows are updated, never
deleted, so progress logs that point at exercises are untouched).
A fresh database needs none of this: startup creates it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text, update  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.models import Exercise, SafetyRule  # noqa: E402
from app.seed import _rows, init_db  # noqa: E402

NEW_COLUMNS = {
    "exercises": {"progression_step": "FLOAT NOT NULL DEFAULT 1", "priority_order": "INTEGER NOT NULL DEFAULT 0"},
    "safety_rules": {"usefulness_rank": "INTEGER"},
}

with engine.begin() as conn:
    inspector = inspect(conn)
    for table, columns in NEW_COLUMNS.items():
        have = {c["name"] for c in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in have:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                print(f"added {table}.{name}")
    case_id = next(c for c in inspector.get_columns("doctor_plans") if c["name"] == "case_id")
    if not case_id["nullable"]:
        if engine.dialect.name != "postgresql":
            sys.exit("doctor_plans.case_id is NOT NULL and SQLite can't change that in place: "
                     "delete the local .db file and restart the backend to recreate it.")
        conn.execute(text("ALTER TABLE doctor_plans ALTER COLUMN case_id DROP NOT NULL"))
        print("doctor_plans.case_id may now be empty")

init_db()  # creates plan_proposals (and turns on RLS for it on Supabase)
with SessionLocal() as db:
    for r in _rows("activity_taxonomy.csv"):
        db.execute(update(Exercise).where(Exercise.activity_type == r["activity_type"]).values(
            progression_step=float(r["progression_step"] or 1), priority_order=int(r["priority_order"] or 0)))
    for r in _rows("safety_grid.csv"):
        db.execute(update(SafetyRule).where(SafetyRule.condition_code == r["condition_code"],
                                            SafetyRule.activity_type == r["activity_type"])
                   .values(usefulness_rank=int(r["usefulness_rank"]) if r["usefulness_rank"] else None))
    db.commit()
print("Filled progression_step, priority_order and usefulness_rank from the CSVs")
