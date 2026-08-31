"""Module 2 rate-limit identity helpers (app/gateway/middleware.py).

Found live (code audit): _client_ip() trusted the LEFTMOST X-Forwarded-For
entry, which is exactly the part of the header a client controls — sending a
fresh fake value on every request landed each request in a different rate
limit bucket and fully defeated rl_ip_per_hour. The fix trusts the RIGHTMOST
entry instead: the one entry a single trusted reverse proxy (Railway/Nginx,
per the app's own comment) appends itself and the client cannot forge.
"""
from app.gateway.middleware import _client_ip


def test_client_ip_trusts_the_rightmost_forwarded_entry(app):
    with app.test_request_context(
        "/", headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.5"}
    ):
        assert _client_ip() == "10.0.0.5"


def test_client_ip_ignores_attacker_supplied_spoofed_prefix(app):
    """The attacker fully controls everything except the last hop — sending a
    different fake leftmost value on every request must not change the
    bucket the real (rightmost) proxy-observed IP maps to."""
    with app.test_request_context(
        "/", headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.5"}
    ):
        first = _client_ip()
    with app.test_request_context(
        "/", headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.5"}
    ):
        second = _client_ip()
    assert first == second == "10.0.0.5"


def test_client_ip_falls_back_to_remote_addr_with_no_forwarded_header(app):
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        assert _client_ip() == "127.0.0.1"


def test_client_ip_handles_a_single_entry_header(app):
    """No proxy chain at all — the one entry present is the rightmost one."""
    with app.test_request_context("/", headers={"X-Forwarded-For": "10.0.0.5"}):
        assert _client_ip() == "10.0.0.5"
