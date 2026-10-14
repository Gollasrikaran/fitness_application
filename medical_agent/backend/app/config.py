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
    # SQLite by default so the project runs with zero setup; point this at
    # Postgres (postgresql+psycopg://...) for a real deployment.
    database_url: str = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'medical_agent.db').as_posix()}")
    # Supabase Auth handles signup, email verification, login and password
    # reset. The backend only verifies the access tokens it issues.
    supabase_url: str = os.environ.get("SUPABASE_URL", "").rstrip("/")
    # Only for projects still on the legacy shared JWT secret (HS256). Newer
    # projects sign with asymmetric keys, verified via the project's JWKS.
    supabase_jwt_secret: str = os.environ.get("SUPABASE_JWT_SECRET", "")
    # Admin-only, used by scripts/create_doctor.py. Never sent to a browser.
    supabase_service_role_key: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    openrouter_api_key: str = os.environ.get("OPENROUTER_API_KEY", "")
    llm_model: str = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")
    llm_timeout_seconds: float = float(os.environ.get("LLM_TIMEOUT_SECONDS", "45"))
    cors_origins: list[str] = field(
        default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174"))
    # How many recent chat messages the agent sees verbatim. Older turns are
    # carried by memory notes instead.
    chat_history_turns: int = int(os.environ.get("CHAT_HISTORY_TURNS", "20"))


settings = Settings()
