"""
Runs scripts/setup_rag_schema.sql against the Supabase database (SUPABASE_DIRECT_URL
in .env.dev — the session pooler connection, needed for DDL since the transaction
pooler doesn't reliably support it). Idempotent: safe to re-run.
"""

from pathlib import Path

import psycopg
from dotenv import dotenv_values

ENV_PATH = Path(__file__).resolve().parent.parent / ".env.dev"
SQL_PATH = Path(__file__).resolve().parent / "setup_rag_schema.sql"


def main():
    env = dotenv_values(ENV_PATH)
    url = env["SUPABASE_DIRECT_URL"].replace("postgresql+psycopg://", "postgresql://")
    sql = SQL_PATH.read_text(encoding="utf-8")

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

    print("rag_chunks table ready.")


if __name__ == "__main__":
    main()
