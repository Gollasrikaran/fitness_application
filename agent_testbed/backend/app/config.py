"""Settings, read once from environment variables (or backend/.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # The live clinic database (the one dataanalysis/ reads). Read-only: every
    # connection is opened with default_transaction_read_only=on.
    clinic_database_url: str = os.environ.get("CLINIC_DATABASE_URL", "").strip().strip('"')
    cors_origins: list[str] = field(
        default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:5175,http://127.0.0.1:5175"))


settings = Settings()
