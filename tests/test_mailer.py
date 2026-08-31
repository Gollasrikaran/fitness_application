"""app/platform/mailer.py — the one seam transactional email goes through.

No real provider is wired up yet (a tracked, deliberate gap pending a
provider decision) — these tests lock in the interim behavior: log the
message in development so a developer can find a token by hand, and never
raise in production (breaking signup/reset over a missing mailer would be
worse than the email just not sending).
"""
import logging

from app.platform.mailer import send_email


def test_logs_at_info_level_in_development(caplog):
    with caplog.at_level(logging.INFO, logger="mailer"):
        send_email(to="a@example.com", subject="Verify", body="token123", is_production=False)
    assert any("token123" in r.message for r in caplog.records)
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_logs_at_error_level_in_production_without_raising(caplog):
    with caplog.at_level(logging.INFO, logger="mailer"):
        send_email(to="a@example.com", subject="Verify", body="token123", is_production=True)
    assert any(r.levelno == logging.ERROR for r in caplog.records)
