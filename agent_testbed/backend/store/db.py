"""The agent's own store: a temporary database (medical_agent's test database),
in its own schema so nothing there is touched. Read and write, unlike the
clinic database.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

SCHEMA = "agent_tmp"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def _url() -> str:
    url = os.getenv("TEMP_DATABASE_URL", "").strip().strip('"')
    if not url:
        raise RuntimeError("TEMP_DATABASE_URL is not set in backend/.env")
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def psycopg_url() -> str:
    """The same database as a plain psycopg URL (for LangGraph's checkpointer)."""
    return _url().replace("postgresql+psycopg://", "postgresql://", 1)


# prepare_threshold=None: required behind Supabase's connection pooler.
engine = create_engine(_url(), pool_pre_ping=True, connect_args={"prepare_threshold": None})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session() -> Iterator[Session]:
    """One transaction: committed on success, rolled back on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
