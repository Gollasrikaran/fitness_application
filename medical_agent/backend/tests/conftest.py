import os
import tempfile
from pathlib import Path

# Must be set before `app` is imported: settings are read at import time.
_tmp = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["OPENROUTER_API_KEY"] = "test-key"
# Tests sign their own HS256 tokens, the way a legacy-secret Supabase project would.
os.environ["SUPABASE_JWT_SECRET"] = "test-supabase-secret"
os.environ["SUPABASE_URL"] = "https://test-project.supabase.co"

import time  # noqa: E402
import uuid  # noqa: E402

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.agent import triage  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402


class FakeLLM:
    """Stands in for OpenRouter: returns `response`, records what it was sent."""

    def __init__(self):
        self.response = {"decision": "self_care", "reply": "Gentle movement should help.", "reason": "minor",
                         "pain_score": None, "suggested_exercises": [], "urgency": "routine",
                         "doctor_summary": None, "new_facts": []}
        self.calls: list[list[dict]] = []
        self.fail = False

    def __call__(self, messages):
        self.calls.append(messages)
        if self.fail:
            raise triage.LLMError("boom")
        return dict(self.response)


@pytest.fixture()
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(triage, "complete_json", fake)
    return fake


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:  # lifespan creates tables and seeds reference data
        yield c


def supabase_token(email, *, sub=None, aud="authenticated", secret="test-supabase-secret", expires_in=3600):
    """A token shaped like the one Supabase Auth issues after login."""
    now = int(time.time())
    claims = {"sub": sub or str(uuid.uuid4()), "aud": aud, "role": "authenticated", "email": email,
              "user_metadata": {"name": email.split("@")[0]}, "iat": now, "exp": now + expires_in}
    return jwt.encode(claims, secret, algorithm="HS256")


def _login(client, email):
    h = {"Authorization": f"Bearer {supabase_token(email)}"}
    assert client.get("/auth/me", headers=h).status_code == 200  # first call creates our users row
    return h


@pytest.fixture()
def patient(client):
    """A patient with chronic back pain and a completed profile."""
    def make(conditions=("chronic_back_pain",), email="pat@example.com"):
        h = _login(client, email)
        r = client.put("/profile", headers=h, json={"age": 34, "sex": "female", "height_cm": 162, "weight_kg": 60,
                                                    "experience": "beginner", "conditions": list(conditions)})
        assert r.status_code == 200, r.text
        return h
    return make


@pytest.fixture()
def doctor(client):
    """Doctors are promoted in our users table (what scripts/create_doctor.py does)."""
    h = _login(client, "doc@example.com")
    with SessionLocal() as db:
        db.query(User).filter(User.email == "doc@example.com").update({"role": "doctor"})
        db.commit()
    return h
