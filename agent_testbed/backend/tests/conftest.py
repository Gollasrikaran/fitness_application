"""The tests run on an in-memory SQLite copy of the reference data, built
from data/*.csv. They never touch a real database or call the AI."""
import os

# Before any app module loads backend/.env: dotenv never overrides a set
# variable, so nothing here can reach the real databases.
for name in ("TEMP_DATABASE_URL", "CLINIC_DATABASE_URL"):
    os.environ[name] = "postgresql://tests@127.0.0.1:1/none"
os.environ["REFERENCE_DATABASE_URL"] = ""
os.environ["OPENROUTER_API_KEY"] = ""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from store.db import SCHEMA, Base
from store.models import Condition, Exercise, ReadingRule, SafetyRule
from store.seed import _from_csv, reading_rules


@pytest.fixture
def db():
    engine = create_engine("sqlite://").execution_options(schema_translate_map={SCHEMA: None})
    Base.metadata.create_all(engine)
    conditions, exercises, rules = _from_csv()
    with Session(engine) as s:
        s.add_all(Condition(**c) for c in conditions.values())
        s.add_all(Exercise(**e) for e in exercises.values())
        s.flush()
        s.add_all(SafetyRule(**r) for r in rules.values())
        s.add_all(ReadingRule(**r) for r in reading_rules())
        s.flush()
        yield s
