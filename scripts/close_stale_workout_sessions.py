"""Workout-session reaper — interim scheduler entry point.

start_workout_session (app/profile/service.py) already self-heals the common
case: starting a new session automatically closes out any session this user
already had marked 'active'. What that doesn't catch is a user who simply
never comes back at all after closing the app mid-workout — their session
would stay 'active' forever, which would (a) permanently block them from ever
starting a new one even weeks later if that check were ever relaxed, and (b)
quietly inflate any future "average session length" or "sessions in
progress" metric with sessions nobody is actually in.

This sweeps anything left 'active' past a generous threshold to 'abandoned'.
Deliberately generous (not "as soon as plausible"): a long but real workout
(stretching, a long walk broken into parts) must not get closed out from
under someone still using it.

Usage: python scripts/close_stale_workout_sessions.py
Suggested cadence: hourly, independent of the daily token/retention jobs.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import update  # noqa: E402

from app.platform.config import load_config  # noqa: E402
from app.platform.db import init_engine, session_scope  # noqa: E402
from app.profile.models import WorkoutSession  # noqa: E402

_log = logging.getLogger(__name__)

# No real guided session (walk, stretch routine, whatever today's program
# contains) plausibly runs this long — past this point it's a closed app, not
# a slow workout.
ABANDON_AFTER = timedelta(hours=3)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    init_engine(cfg.database_url)

    cutoff = datetime.now(timezone.utc) - ABANDON_AFTER

    with session_scope() as session:
        result = session.execute(
            update(WorkoutSession)
            .where(WorkoutSession.status == "active", WorkoutSession.started_at < cutoff)
            .values(status="abandoned", ended_at=WorkoutSession.started_at + ABANDON_AFTER)
        )
        closed = result.rowcount

    _log.info(
        "close_stale_workout_sessions: closed %d session(s) started before %s",
        closed, cutoff.isoformat(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
