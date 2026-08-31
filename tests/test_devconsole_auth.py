"""app/devconsole/routes.py's independent auth layer.

Found live (third-pass code audit): requiring FLASK_ENV to be set
explicitly (app/platform/config.py) only closes the "forgot to set it,
silently defaulted to dev" failure mode. "development" and "test" are both
legitimate non-production FLASK_ENV values, so a box deliberately or
accidentally started with either — but still network-reachable (a staging
URL, a preview deploy) — would leave the entire devconsole blueprint open
with no login of its own: /app is a full working clone of the mobile client
wired to the real signup/login/refresh/logout endpoints, /dev logs raw
request/response bodies including tokens. devconsole now requires its own
HTTP Basic Auth credentials, independent of FLASK_ENV/is_production, and
fails closed (refuses everything) if no password is configured at all.
"""
import base64

import pytest


def _basic(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def devconsole_app(monkeypatch):
    monkeypatch.setenv("DEVCONSOLE_USER", "admin")
    monkeypatch.setenv("DEVCONSOLE_PASSWORD", "a-real-test-password")
    from app import create_app
    return create_app()


def test_devconsole_refuses_requests_with_no_credentials(devconsole_app):
    client = devconsole_app.test_client()
    r = client.get("/dev")
    assert r.status_code == 401


def test_devconsole_refuses_wrong_password(devconsole_app):
    client = devconsole_app.test_client()
    r = client.get("/dev", headers=_basic("admin", "wrong-password"))
    assert r.status_code == 401


def test_devconsole_accepts_correct_credentials(devconsole_app):
    client = devconsole_app.test_client()
    r = client.get("/dev", headers=_basic("admin", "a-real-test-password"))
    assert r.status_code == 200


def test_devconsole_app_route_also_gated(devconsole_app):
    """Not just /dev — every route in the blueprint goes through the same
    before_request hook."""
    client = devconsole_app.test_client()
    assert client.get("/app").status_code == 401
    assert client.get("/app", headers=_basic("admin", "a-real-test-password")).status_code == 200


def test_devconsole_fails_closed_with_no_password_configured(monkeypatch):
    """Blank/unset DEVCONSOLE_PASSWORD must refuse everything outright, not
    silently allow access — this is the actual production posture today
    since no password is configured anywhere except local dev's .env.dev."""
    monkeypatch.delenv("DEVCONSOLE_USER", raising=False)
    monkeypatch.delenv("DEVCONSOLE_PASSWORD", raising=False)
    from app import create_app
    app = create_app()
    client = app.test_client()
    r = client.get("/dev")
    assert r.status_code == 403
