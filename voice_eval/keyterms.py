"""The vocabulary we hint to models that accept one (e.g. Sarvam v4 `keyterms`).

Read-only from the app's own reviewed CSVs, so the hint list always matches
what the app can actually log — nothing here edits data/.
"""
from __future__ import annotations

import csv
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# Units and counting words people say when logging; cheap to include and
# they're exactly the tokens a misheard number hides behind.
UNIT_TERMS = ["km", "reps", "sets", "minutes", "seconds"]


def build_keyterms(limit: int = 50) -> list[str]:
    """Priority order, since vendors cap the list: units, exercise display
    names, condition names, then exercise synonyms. Deduped case-insensitively."""
    with (DATA / "activity_taxonomy.csv").open(encoding="utf-8") as f:
        activities = list(csv.DictReader(f))
    with (DATA / "conditions.csv").open(encoding="utf-8") as f:
        conditions = [r for r in csv.DictReader(f) if r["condition_code"] != "none"]

    ordered = list(UNIT_TERMS)
    ordered += [a["display_name"] for a in activities]
    ordered += [c["display_name"] for c in conditions]
    ordered += [s for a in activities for s in a["synonyms"].split("|")]

    seen, out = set(), []
    for term in ordered:
        term = term.strip()
        if term and len(term) <= 64 and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out[:limit]


if __name__ == "__main__":
    for t in build_keyterms():
        print(t)
