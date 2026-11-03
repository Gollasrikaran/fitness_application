"""Client for the colleague's Patient Intelligence API (read-only).

Only the GET endpoints our key may call (PATIENT_API_FINDINGS.md). Never
POST /review: it runs the AI and costs the clinic money. The URL and key come
from backend/.env (PATIENT_API_URL, PATIENT_API_KEY); the URL changes when the
API restarts.
"""
from __future__ import annotations

import logging
import time

import httpx

from app.config import settings

log = logging.getLogger("patient_api")

_RETRIES = 3


class PatientApiError(Exception):
    pass


_client = httpx.Client(timeout=60, headers={"X-API-Key": settings.patient_api_key})


def get(path: str, **params) -> dict | list | None:
    """GET one endpoint. None for a 404 (unknown patient); PatientApiError when
    the API can't be reached or refuses the request."""
    if not settings.patient_api_url:
        raise PatientApiError("PATIENT_API_URL is not set in backend/.env")
    last = ""
    for attempt in range(_RETRIES):
        try:
            r = _client.get(settings.patient_api_url + path, params=params or None)
        except httpx.HTTPError as exc:
            last = f"unreachable ({type(exc).__name__}): is the API running, and is PATIENT_API_URL current?"
        else:
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code in (401, 403, 422):
                raise PatientApiError(f"{r.status_code} on {path}: {r.text[:200]}")
            last = f"{r.status_code} on {path}"
        time.sleep(1 + attempt)
    log.error("Patient API %s: %s", path, last)
    raise PatientApiError(f"Patient API {last}")


def health() -> bool:
    try:
        return (get("/health") or {}).get("status") == "ok"
    except PatientApiError:
        return False
