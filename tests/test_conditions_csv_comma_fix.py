"""Regression test for a found-live bug: data/conditions.csv's 'neurological'
row had an unquoted comma in its notes field ("Multiple sclerosis, neuropathy,
and similar."), so csv.DictReader split it into extra unnamed columns and
load_conditions() silently truncated notes down to just "Multiple sclerosis".
Fixed by quoting the field, matching the convention already used by the
'diabetes'/'high_bp' rows, which also have commas in their notes."""
import csv

from app.catalog.loader import DATA
from app.catalog.models import Condition
from app.platform.db import session_scope


def test_conditions_csv_has_no_misaligned_rows():
    rows = list(csv.DictReader((DATA / "conditions.csv").open(encoding="utf-8")))
    misaligned = [r["condition_code"] for r in rows if None in r]
    assert misaligned == [], f"unquoted commas split these rows: {misaligned}"


def test_neurological_notes_are_not_truncated(client):
    with session_scope() as s:
        row = s.get(Condition, "neurological")
        assert row is not None
        assert row.notes == "Multiple sclerosis, neuropathy, and similar."
