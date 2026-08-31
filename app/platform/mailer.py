"""Transactional email — one seam every part of the app sends through.

No real provider is wired up yet. That's a deliberate, tracked gap (product
decision: pick a provider — Resend, SendGrid, SES are all reasonable — once
that's chosen, before real users need to verify an email or reset a
password). Everything routes through send_email() so wiring in a real
provider later is one function body here, not a hunt through every call site
that used to do its own ad hoc logging (found live, code audit:
app/auth/routes.py had two separate inline `if not cfg.is_production:
logger.info(...)` blocks, and in production did nothing at all — no log, no
send, totally silent).

In development/test, the message is logged so a developer can find the
token by hand, matching the previous behavior. In production, this logs
loudly at ERROR level instead of raising: losing an email delivery is bad,
but breaking the signup/reset request that's waiting on it — turning a
missing-mailer configuration gap into an outage — would be worse. AppIssue
(app/platform/models.py) is deliberately not used here: its own docstring
scopes it narrowly to genuine unexpected errors and two specific named
events, not a known, already-tracked configuration gap like this one.
"""
from __future__ import annotations

import logging

_log = logging.getLogger("mailer")


def send_email(*, to: str, subject: str, body: str, is_production: bool) -> None:
    """TODO(launch-blocker): replace this body with a real provider call
    once one is chosen. Keep the signature — every call site already passes
    exactly what a real provider needs (a recipient, a subject, a body)."""
    if not is_production:
        _log.info("MAILER (not yet configured) -> to=%s subject=%r body=%s", to, subject, body)
        return
    _log.error(
        "MAILER NOT CONFIGURED in production — email to %s was NOT sent: subject=%r",
        to, subject,
    )
