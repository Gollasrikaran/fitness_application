"""Shared fixtures for the RAG (Module 5) test suite.

Runs against your real local Postgres + the real Supabase rag_chunks database +
the real OpenRouter API — these are integration tests, not mocked unit tests, by
design: the whole point is to catch real regressions in the actual pipeline.
"""
import os
import uuid

import pytest
from dotenv import dotenv_values

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def _load_env():
    env = dotenv_values(os.path.join(ROOT, ".env.dev"))
    os.environ.setdefault("FLASK_ENV", "development")
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/fitness"
    )
    os.environ.setdefault("BREACH_CHECK_ENABLED", "false")
    os.environ["RAG_DATABASE_URL"] = env.get("SUPABASE_DIRECT_URL", "")
    os.environ["OPENROUTER_API_KEY"] = env.get("OPENROUTER_API_KEY", "")


@pytest.fixture(scope="session")
def app():
    from app import create_app
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(client):
    """Factory fixture. Call as make_user(condition_codes=["gout"]) and get back
    {"headers": <auth headers for HTTP calls>, "user_id": <for direct DB/service
    calls>}."""
    def _make(condition_codes=None, age=30, goal="health", experience_band="beginner"):
        # A per-test counter combined with whole-second time collided across
        # different tests that each made their first user in the same second
        # (both got "n=1" at the same truncated timestamp) — a real uuid can't
        # collide regardless of timing.
        unique = uuid.uuid4().hex[:12]
        email = f"pytest.{unique}@example.com"
        device_headers = {"X-Device-Id": f"pytest-device-{unique}"}
        r = client.post(
            "/v1/auth/signup",
            json={"email": email, "password": "a-good-long-passphrase-123"},
            headers=device_headers,
        )
        assert r.status_code == 201, r.get_json()
        body = r.get_json()
        auth_headers = {**device_headers, "Authorization": f"Bearer {body['access_token']}"}
        client.post(
            "/v1/profile/onboarding",
            json={
                "age": age, "goal": goal, "experience_band": experience_band,
                "condition_codes": condition_codes or ["none"], "unit_preference": "km",
            },
            headers=auth_headers,
        )
        return {"headers": auth_headers, "user_id": body["user_id"]}

    return _make
