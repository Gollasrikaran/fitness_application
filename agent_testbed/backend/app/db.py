"""Read-only connection pool to the live clinic database."""
from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings


def _read_only(conn) -> None:
    # Production data: every transaction starts as READ ONLY, so the database
    # itself refuses any write. (A "-c default_transaction_read_only=on"
    # startup option is silently dropped by Supabase's pooler.)
    conn.read_only = True


pool = ConnectionPool(
    settings.clinic_database_url.replace("postgresql+psycopg://", "postgresql://"),
    min_size=1,
    max_size=8,
    open=False,
    configure=_read_only,
    # Required behind Supabase's connection pooler.
    kwargs={"prepare_threshold": None, "row_factory": dict_row},
)


def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params or {}).fetchall()


def fetch_one(sql: str, params: dict | None = None) -> dict | None:
    with pool.connection() as conn:
        return conn.execute(sql, params or {}).fetchone()
