"""Create the agent_tmp schema and tables, and load the reference data from
data/*.csv (copies of medical_agent's). Safe to run on every start."""
from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select, text

from store.db import SCHEMA, Base, engine, session
from store.models import Condition, Exercise, SafetyRule

DATA = Path(__file__).resolve().parent.parent / "data"


def _rows(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def init_store() -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:  # keep the tables out of Supabase's public Data API
        for table in Base.metadata.sorted_tables:
            conn.execute(text(f'ALTER TABLE "{SCHEMA}"."{table.name}" ENABLE ROW LEVEL SECURITY'))
    with session() as db:
        if db.scalar(select(Condition).limit(1)) is None:
            _load_reference(db)


def _load_reference(db) -> None:
    for r in _rows("conditions.csv"):
        db.add(Condition(code=r["condition_code"], display_name=r["display_name"], bucket=r["bucket"],
                         display_order=int(r["display_order"] or 0)))
    for r in _rows("activity_taxonomy.csv"):
        db.add(Exercise(activity_type=r["activity_type"], display_name=r["display_name"],
                        amount_unit=r["amount_unit"], default_sets=int(r["default_sets"] or 1),
                        default_amount=float(r["default_amount"] or 1),
                        progression_step=float(r["progression_step"] or 1),
                        priority_order=int(r["priority_order"] or 0),
                        synonyms=[s.strip().lower() for s in (r.get("synonyms") or "").split("|") if s.strip()]))
    db.flush()
    for r in _rows("safety_grid.csv"):
        db.add(SafetyRule(condition_code=r["condition_code"], activity_type=r["activity_type"],
                          verdict=r["verdict"], note=r["note"],
                          usefulness_rank=int(r["usefulness_rank"]) if r["usefulness_rank"] else None))
