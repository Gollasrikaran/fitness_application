"""Verifies Supabase Auth access tokens and maps them to our own users.

Supabase owns identity (email, password, verification). We own the role:
the `users` table here says who is a patient and who is a doctor, so a user
can't promote themselves by editing their Supabase profile.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

log = logging.getLogger("medical_agent.auth")

_bearer = HTTPBearer(auto_error=False)
AUDIENCE = "authenticated"  # what Supabase puts in tokens for signed-in users


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    if not settings.supabase_url:
        raise RuntimeError("SUPABASE_URL is not set")
    # Public signing keys. Cached client (lru_cache) so keys aren't re-downloaded
    # on every request; PyJWKClient refetches on its own when a new key id appears.
    return jwt.PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True)


def verify_token(token: str) -> dict:
    """Claims of a valid Supabase access token; raises jwt.PyJWTError otherwise."""
    alg = jwt.get_unverified_header(token).get("alg")
    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise jwt.InvalidTokenError("HS256 token but SUPABASE_JWT_SECRET is not set")
        return jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience=AUDIENCE)
    key = _jwks_client().get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["ES256", "RS256"], audience=AUDIENCE)


def _name_from(claims: dict) -> str:
    meta = claims.get("user_metadata") or {}
    return (meta.get("name") or meta.get("full_name") or claims.get("email", "").split("@")[0] or "User")[:128]


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    try:
        claims = verify_token(creds.credentials)
    except jwt.PyJWKClientConnectionError as exc:
        # Couldn't download Supabase's signing keys: a network problem, not a bad login.
        log.error("Can't reach Supabase to verify a login: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Can't reach the login server right now. Check your internet connection and try again.")
    except (jwt.PyJWTError, RuntimeError) as exc:
        log.info("Login token rejected: %s", exc.__class__.__name__)  # never log the token itself
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again")

    user = db.get(User, claims["sub"])
    if user is None:
        # First request after a Supabase signup: create our side of the account.
        # Everyone starts as a patient; doctors are promoted by scripts/create_doctor.py.
        user = User(id=claims["sub"], email=(claims.get("email") or "").lower(), name=_name_from(claims),
                    role="patient")
        db.add(user)
        db.flush()
    return user


def require_patient(user: User = Depends(current_user)) -> User:
    if user.role != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Patients only")
    return user


def require_doctor(user: User = Depends(current_user)) -> User:
    if user.role != "doctor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Doctors only")
    return user
