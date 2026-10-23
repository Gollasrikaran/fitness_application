"""Read the exercise reference data from the reference database (a
colleague's Supabase project). Read-only: we may not write or create tables
there. Only read at startup, by store.seed.
"""
from __future__ import annotations

import logging
import os

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("store.reference")


def _url() -> str:
    url = os.getenv("REFERENCE_DATABASE_URL", "").strip().strip('"')
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def fetch() -> dict[str, list[dict]] | None:
    """{"conditions", "exercises", "rules"} from the reference DB, or None
    when it isn't configured or can't be reached."""
    url = _url()
    if not url:
        log.warning("REFERENCE_DATABASE_URL is not set: using data/*.csv only")
        return None
    try:
        # prepare_threshold=None: required behind Supabase's connection pooler.
        with psycopg.connect(url, prepare_threshold=None, row_factory=dict_row, connect_timeout=15) as conn:
            conn.read_only = True
            return {
                "conditions": conn.execute("""
                    SELECT condition_code, display_name, bucket, display_order, coalesce(notes, '') AS notes
                    FROM conditions""").fetchall(),
                "exercises": conn.execute("""
                    SELECT activity_type, display_name, prescription_type, amount_unit, default_sets,
                           default_amount::float AS default_amount, max_sets, max_amount::float AS max_amount,
                           per_side, rest_seconds, progression_step::float AS progression_step, priority_order,
                           coalesce(instructions, '{}') AS instructions, coalesce(demo_images, '{}') AS images
                    FROM activity_taxonomy""").fetchall(),
                "rules": conn.execute("""
                    SELECT condition_code, activity_type, verdict, coalesce(note, '') AS note
                    FROM safety_grid""").fetchall(),
            }
    except Exception as exc:
        log.warning("Reference DB unreachable, using data/*.csv only: %s", exc)
        return None
