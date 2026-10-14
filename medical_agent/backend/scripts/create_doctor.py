"""Create (or promote) a doctor account. Admin-only: uses the service role key.

    python scripts/create_doctor.py doctor@example.com "Dr Asha Rao"

- New email: creates the account in Supabase Auth, already email-verified,
  with a temporary password printed once. The doctor changes it via
  "Forgot password" on the doctor login page.
- Existing Supabase account (e.g. someone who signed up as a patient):
  promotes it to doctor in our users table.
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.seed import init_db  # noqa: E402


def _headers() -> dict:
    key = settings.supabase_service_role_key
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):  # legacy JWT-style service_role key; new sb_secret_ keys go in apikey only
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _find_auth_user(email: str) -> dict | None:
    page = 1
    while True:
        r = httpx.get(f"{settings.supabase_url}/auth/v1/admin/users", headers=_headers(),
                      params={"page": page, "per_page": 200}, timeout=30)
        r.raise_for_status()
        users = r.json().get("users", [])
        for u in users:
            if (u.get("email") or "").lower() == email:
                return u
        if len(users) < 200:
            return None
        page += 1


def main(email: str, name: str) -> None:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        sys.exit("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env first.")
    email = email.lower()
    temp_password = None

    auth_user = _find_auth_user(email)
    if auth_user is None:
        temp_password = secrets.token_urlsafe(12)
        r = httpx.post(f"{settings.supabase_url}/auth/v1/admin/users", headers=_headers(), timeout=30,
                       json={"email": email, "password": temp_password, "email_confirm": True,
                             "user_metadata": {"name": name}})
        if r.status_code >= 300:
            sys.exit(f"Supabase refused to create the user: HTTP {r.status_code} {r.text[:300]}")
        auth_user = r.json()

    init_db()
    with SessionLocal() as db:
        user = db.get(User, auth_user["id"]) or db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(id=auth_user["id"], email=email, name=name, role="doctor")
            db.add(user)
        else:
            user.role, user.name = "doctor", name
        db.commit()

    print(f"{email} is now a doctor.")
    if temp_password:
        print(f"Temporary password (shown once, share it privately): {temp_password}")
        print("They can log in at /doctor and change it with 'Forgot password'.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
