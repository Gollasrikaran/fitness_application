"""One-off backfill for a found-live bug, now fixed at the source (see
app/progression/service.py's _round_reps / start_per_set_tracking_if_needed /
_sync_entry_from_sets): a reps-type activity's per-set targets used to be
stored with a generic round(v, 2), showing a Workout Player set as "12.34"
reps instead of a whole number nobody can actually perform.

The code fix only prevents NEW fractional values from being written — it does
nothing for rows already saved before the fix was deployed. This script finds
every reps-type UserProgram row still holding a fractional set_targets value
and rounds it the same half-up way the real fix does, so no stale pre-fix data
is left showing a fractional rep count in production.

Safe to run more than once (idempotent — a row already whole is left alone)
and safe to run against any environment by pointing DATABASE_URL at it first.

Usage: python scripts/fix_fractional_reps_set_targets.py [--dry-run]
"""
from __future__ import annotations

import logging
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.catalog.models import ActivityTaxonomy  # noqa: E402
from app.platform.config import load_config  # noqa: E402
from app.platform.db import init_engine, session_scope  # noqa: E402
from app.profile.models import UserProgram  # noqa: E402
from app.progression.service import _round_reps  # noqa: E402

_log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dry_run = "--dry-run" in sys.argv
    cfg = load_config()
    init_engine(cfg.database_url)

    fixed = 0
    with session_scope() as session:
        rows = session.scalars(
            select(UserProgram)
            .join(ActivityTaxonomy, ActivityTaxonomy.activity_type == UserProgram.activity_type)
            .where(
                ActivityTaxonomy.prescription_type == "reps",
                UserProgram.set_targets.is_not(None),
            )
        ).all()
        for entry in rows:
            rounded = [Decimal(str(_round_reps(float(v)))) for v in entry.set_targets]
            if rounded == list(entry.set_targets):
                continue
            _log.info(
                "user_id=%s activity_type=%s set_targets %s -> %s",
                entry.user_id, entry.activity_type, entry.set_targets, rounded,
            )
            fixed += 1
            if not dry_run:
                entry.set_targets = rounded

    _log.info(
        "fix_fractional_reps_set_targets: %s %d row(s) with fractional set_targets",
        "would fix" if dry_run else "fixed", fixed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
