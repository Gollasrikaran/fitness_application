"""Newer Supabase projects sign access tokens with an asymmetric key (ES256)
published at /auth/v1/.well-known/jwks.json, instead of a shared secret."""
import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from app import auth


class _FakeJWKS:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return type("Key", (), {"key": self.public_key})()


def _es256_token(private_key, aud="authenticated"):
    now = int(time.time())
    return jwt.encode({"sub": str(uuid.uuid4()), "aud": aud, "email": "es@example.com", "iat": now,
                       "exp": now + 3600}, private_key, algorithm="ES256", headers={"kid": "k1"})


def test_es256_tokens_verified_with_project_jwks(client, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(auth, "_jwks_client", lambda: _FakeJWKS(key.public_key()))
    ok = client.get("/auth/me", headers={"Authorization": f"Bearer {_es256_token(key)}"})
    assert ok.status_code == 200 and ok.json()["email"] == "es@example.com"

    other = ec.generate_private_key(ec.SECP256R1())  # signed by someone else's key
    bad = client.get("/auth/me", headers={"Authorization": f"Bearer {_es256_token(other)}"})
    assert bad.status_code == 401


def test_unreachable_supabase_is_503_not_401(client, monkeypatch):
    class _Down:
        def get_signing_key_from_jwt(self, token):
            raise jwt.PyJWKClientConnectionError("timed out")
    monkeypatch.setattr(auth, "_jwks_client", lambda: _Down())
    key = ec.generate_private_key(ec.SECP256R1())
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {_es256_token(key)}"})
    assert r.status_code == 503 and "login server" in r.json()["detail"]
