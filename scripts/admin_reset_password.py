"""Manual password reset — the stand-in for the email-based flow until a real
mail provider is wired up (app/platform/mailer.py is a stub that drops every
email in production, so /v1/auth/password-reset/* is currently unusable by a
locked-out user on their own).

This does exactly what confirm_password_reset() would have done, minus the
emailed token: set a new password hash, revoke every existing session, and
clear any login-lockout counter — run by whoever operates this app, after
verifying the requester's identity through some channel outside the app
(WhatsApp, in person, whatever "contact us" actually means for this project).

Usage:
    python scripts/admin_reset_password.py user@example.com

You'll be prompted for the new password (not taken as a CLI argument, so it
never ends up in your shell history). Requires the same env vars as any other
script here (DATABASE_URL, REDIS_DURABLE_URL, REDIS_CACHE_URL, FLASK_ENV).
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.auth import tokens as tk  # noqa: E402
from app.auth.models import User  # noqa: E402
from app.auth.passwords import hash_password, validate_password  # noqa: E402
from app.platform import redis_clients as rc  # noqa: E402
from app.platform.config import load_config  # noqa: E402
from app.platform.db import init_engine, session_scope  # noqa: E402
from app.platform.errors import ValidationError  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/admin_reset_password.py <email>")
        return 1
    email = sys.argv[1].strip().lower()

    cfg = load_config()
    init_engine(cfg.database_url)
    # allow_fallback=False deliberately, even outside production. This script
    # exists to get a locked-out user back in, and two of the three things it
    # does (clearing the lockout counter, invalidating outstanding access
    # tokens) are Redis writes. With the in-memory dev fallback those writes
    # would go to a throwaway store that dies with this process — the
    # password would change in the real database while the user stayed
    # locked out and old sessions stayed valid, with no error shown. That is
    # the exact failure this tool is meant to fix, so refuse to run without
    # the real Redis rather than half-succeed silently.
    rc.init_redis(cfg.redis_durable_url, cfg.redis_cache_url, allow_fallback=False)

    new_password = getpass.getpass("New password for this account: ")
    confirm = getpass.getpass("Confirm: ")
    if new_password != confirm:
        print("Passwords did not match. Nothing changed.")
        return 1

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email))
        if user is None or not user.is_active:
            print(f"No active account found for {email!r}. Nothing changed.")
            return 1

        try:
            validate_password(
                new_password,
                min_length=cfg.password_min_length,
                breach_check=cfg.breach_check_enabled,
            )
        except ValidationError as exc:
            print(f"Rejected: {exc.message}")
            return 1

        user.password_hash = hash_password(new_password)
        # Same cleanup confirm_password_reset() does: kill every existing
        # session so a device that had the OLD password can't keep using it,
        # and clear any lockout counter so the user isn't still locked out
        # right after you just fixed the thing that locked them out.
        tk.revoke_all_refresh_tokens(session, user.id)
        tk.set_tokens_valid_after(user.id, cfg)
        rc.durable().delete(rc.key_login_failures(user.id))

    print(f"Password reset for {email!r}. All existing sessions were signed out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
