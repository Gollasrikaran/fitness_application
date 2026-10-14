"""Print every table's columns, row count and foreign keys. Read-only.

    python scripts/inspect_db.py                 # uses DATABASE_URL from backend/.env
    python scripts/inspect_db.py ../../.env.dev  # or the DATABASE_URL from another env file

Reads structure only: it never selects the data inside the tables.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values

env_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / ".env"
url = dotenv_values(env_file).get("DATABASE_URL")
if not url:
    sys.exit(f"No DATABASE_URL in {env_file}")
url = url.replace("postgresql+psycopg://", "postgresql://")  # psycopg wants the plain form

TABLES = """select table_name from information_schema.tables
            where table_schema = 'public' and table_type = 'BASE TABLE' order by 1"""
COLUMNS = """select column_name, data_type, is_nullable, column_default
             from information_schema.columns
             where table_schema = 'public' and table_name = %s order by ordinal_position"""
FOREIGN_KEYS = """
    select tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name
    from information_schema.table_constraints tc
    join information_schema.key_column_usage kcu
      on tc.constraint_name = kcu.constraint_name and tc.table_schema = kcu.table_schema
    join information_schema.constraint_column_usage ccu
      on tc.constraint_name = ccu.constraint_name and tc.table_schema = ccu.table_schema
    where tc.constraint_type = 'FOREIGN KEY' and tc.table_schema = 'public' order by 1, 2"""

# prepare_threshold=None: needed behind Supabase's connection pooler (port 6543).
with psycopg.connect(url, connect_timeout=10, prepare_threshold=None) as conn:
    conn.read_only = True  # the database itself refuses any write in this session
    tables = [row[0] for row in conn.execute(TABLES)]
    print(f"{len(tables)} tables\n")
    for table in tables:
        count = conn.execute(f'select count(*) from public."{table}"').fetchone()[0]
        print(f"== {table}  ({count} rows)")
        for name, dtype, nullable, default in conn.execute(COLUMNS, (table,)):
            flags = ("" if nullable == "YES" else "NOT NULL") + (f"  default={default[:30]}" if default else "")
            print(f"   {name:<28} {dtype:<26} {flags}")
    print("\n== foreign keys")
    for src_table, src_col, dst_table, dst_col in conn.execute(FOREIGN_KEYS):
        print(f"   {src_table}.{src_col} -> {dst_table}.{dst_col}")
