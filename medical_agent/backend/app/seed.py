"""Create tables and load reference data from backend/data/*.csv.

The CSVs are copies of the main app's reviewed files (data/ at the repo
root). Re-running is safe: reference rows are replaced, user data is kept.

    python -m app.seed
"""
from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import Condition, Exercise, SafetyRule

DATA = Path(__file__).resolve().parent.parent / "data"


def _rows(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_reference_data(db: Session) -> dict[str, int]:
    db.execute(delete(SafetyRule))
    db.execute(delete(Exercise))
    db.execute(delete(Condition))
    db.flush()

    for r in _rows("conditions.csv"):
        db.add(Condition(code=r["condition_code"], display_name=r["display_name"],
                         bucket=r["bucket"], display_order=int(r["display_order"] or 0)))
    for r in _rows("activity_taxonomy.csv"):
        db.add(Exercise(activity_type=r["activity_type"], display_name=r["display_name"],
                        amount_unit=r["amount_unit"], default_sets=int(r["default_sets"] or 1),
                        default_amount=float(r["default_amount"] or 1),
                        per_side=r.get("per_side", "").lower() in ("true", "1", "yes")))
    db.flush()
    rules = _rows("safety_grid.csv")
    for r in rules:
        db.add(SafetyRule(condition_code=r["condition_code"], activity_type=r["activity_type"],
                          verdict=r["verdict"], note=r["note"]))
    return {"conditions": len(_rows("conditions.csv")),
            "exercises": len(_rows("activity_taxonomy.csv")), "safety_rules": len(rules)}


def init_db() -> None:
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        lock_down_data_api()


def lock_down_data_api() -> None:
    """On Supabase, every table in `public` is reachable through the REST Data
    API with the anon key — which the frontend ships to every browser. RLS
    with no policies blocks that path entirely. The backend still has full
    access: it connects as the tables' owner, and owners bypass RLS."""
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            conn.exec_driver_sql(f'ALTER TABLE public."{table.name}" ENABLE ROW LEVEL SECURITY')


if __name__ == "__main__":
    init_db()
    with SessionLocal() as session:
        counts = load_reference_data(session)
        session.commit()
    print("Seeded:", counts)
