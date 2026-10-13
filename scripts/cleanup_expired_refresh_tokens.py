"""Refresh-token reaper — interim scheduler entry point.

Every login/refresh inserts a new row into refresh_tokens and never deletes the
old one (rotation keeps the prior row around, superseded, as its own history).
Nothing else in this codebase ever cleans that table up, so it grows roughly
one row per rotation per user forever — for a daily-active user that is on the
order of tens of thousands of rows a year, on a table with a unique index on
token_hash.

What this deletes, and why it is NOT simply "expired" rows:
sessions are configured to last effectively forever (REFRESH_TOKEN_TTL_DAYS
defaults to 3650 — the product decision that a user stays signed in until they
choose to log out), so `expires_at < now()` matches essentially nothing and a
reaper written that way would be a permanent no-op. The rows that actually
accumulate are DEAD ones: superseded by rotation (`rotated_at`) or explicitly
revoked (`revoked_at`). Those are what this removes, after a retention window.

Why a retention window rather than deleting dead rows immediately: theft
detection works by recognising a *reused* rotated/revoked token
(app/auth/tokens.py). Deleting such a row instantly would downgrade that
signal — a replayed stolen token would look like an unknown token (plain 401)
instead of triggering the full theft response. Keeping dead rows for
RETENTION_DAYS preserves detection for anything recent, which is the window
where a replay realistically matters, while still bounding the table.

Usage: python scripts/cleanup_expired_refresh_tokens.py
Suggested cadence: daily, same as the weekly-progression job.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, or_  # noqa: E402

from app.auth.models import RefreshToken  # noqa: E402
from app.platform.config import load_config  # noqa: E402
from app.platform.db import init_engine, session_scope  # noqa: E402

_log = logging.getLogger(__name__)

# How long a dead (rotated or revoked) row is kept before deletion, so token
# replay in that window still trips theft detection rather than looking like
# an unknown token. See the module docstring.
#
# Sized against the session lifetime, not picked as a round number. Sessions
# are configured to last ~10 years (REFRESH_TOKEN_TTL_DAYS), so a token
# skimmed off a lost device stays presentable for that whole period — and a
# short retention here would mean an attacker only has to WAIT for the row to
# be reaped, after which replaying it returns a plain 401 instead of tripping
# handle_theft (which revokes the victim's other sessions, drops their push
# tokens and files a security issue). A year keeps detection meaningful for
# the window in which a replay realistically happens, while still bounding
# the table. If session lifetime is ever shortened, shorten this with it —
# the two settings belong together.
RETENTION_DAYS = 365


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    init_engine(cfg.database_url)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RETENTION_DAYS)

    with session_scope() as session:
        result = session.execute(
            delete(RefreshToken).where(
                or_(
                    # Dead: superseded by rotation, or explicitly revoked —
                    # this is the growth, one row per refresh, forever.
                    RefreshToken.rotated_at < cutoff,
                    RefreshToken.revoked_at < cutoff,
                    # Genuinely expired. Effectively unreachable while
                    # sessions are configured to last ~10 years, but correct
                    # for any row issued under a shorter TTL, and stays
                    # correct if that setting is ever lowered again.
                    RefreshToken.expires_at < now,
                )
            )
        )
        deleted = result.rowcount

    _log.info(
        "cleanup_expired_refresh_tokens: deleted %d dead row(s) "
        "(rotated/revoked before %s, or already expired)",
        deleted, cutoff.date(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
