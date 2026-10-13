"""Module 2 — auth middleware and rate limiting.

This is middleware applied at the edge, not a service. No business module imports it.

2.3 — three independent limits. Per-device and per-IP are enforced SEPARATELY on
pre-auth endpoints: a single combined key would let an attacker reset the counter
by cycling device IDs, which defeats the IP backstop entirely.
"""
from __future__ import annotations

import functools
from typing import Callable

from flask import current_app, g, request

from app.auth import tokens as tk
from app.platform import redis_clients as rc
from app.platform.errors import Forbidden, RateLimited, Unauthorized


def _client_ip() -> str:
    # Trust the platform's forwarded header; Railway/Nginx sets it. Take the
    # RIGHTMOST entry, not the leftmost (found live, code audit): each hop
    # APPENDS the IP it directly observed, so the last entry is the one the
    # trusted proxy itself saw on the wire and the client cannot forge — the
    # leftmost entries are whatever the client chose to send, and trusting
    # them let an attacker reset this limiter every request by sending a
    # fresh fake value. This assumes exactly one trusted proxy hop in front
    # of the app (Railway/Nginx); if a CDN or a second proxy is ever added
    # in front of that, this needs to skip that many more trailing entries.
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.remote_addr or "unknown"


def _device_id() -> str:
    """Stable per-install identifier from the client (1.4). Never an IP.

    Unlike _client_ip, there is no server-observed value to fall back on
    here — this is a bare client-supplied header with no cryptographic
    binding to a real device (found live, code audit: sending a fresh random
    value per request bypasses rl_device_per_hour entirely). A real fix needs
    a server-issued, signed device credential established during a prior
    authenticated step, which is a bigger feature than this rate limiter can
    fix on its own. The corrected _client_ip above is the limiter that
    actually holds against a spoofing attacker; this one is defense-in-depth
    against a legitimate client's own bug (e.g. regenerating an id on every
    launch), not a hard guarantee against a deliberate attacker.
    """
    header = request.headers.get("X-Device-Id", "").strip()
    if header:
        return header
    # Found live (code audit): falling back to one shared literal string here
    # meant EVERY caller that omits this header — across signup, login,
    # verify-email, both password-reset routes, everything gated by
    # enforce_preauth_rate_limits() — collapsed into a single rate-limit
    # bucket at rl_device_per_hour (default 60/hour). 60 requests from any
    # one anonymous source, anywhere, could exhaust password-reset and
    # email-verification for the entire app at once. Keying the fallback on
    # the caller's own IP instead means unrelated anonymous callers no longer
    # share a bucket with each other. This is not a security fix by itself —
    # this function's own docstring already covers why device-id can't be
    # trusted against a deliberate attacker — it only closes the specific
    # "one bucket for the whole world" failure mode. rl_ip_per_hour remains
    # the real backstop either way.
    return f"no-device:{_client_ip()}"


def _incr_window(key: str, limit: int, window_seconds: int) -> None:
    r = rc.durable()
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.ttl(key)
    count, ttl = pipe.execute()
    if ttl is None or ttl < 0:
        r.expire(key, window_seconds)
        ttl = window_seconds
    if count > limit:
        raise RateLimited(
            "Too many requests. Please slow down.",
            retry_after=max(int(ttl), 1),
        )


def enforce_preauth_rate_limits() -> None:
    """Signup / login / reset. Both limits must pass — they are not merged."""
    cfg = current_app.config["APP_CONFIG"]
    _incr_window(rc.key_rl_device(_device_id()), cfg.rl_device_per_hour, 3600)
    _incr_window(rc.key_rl_ip(_client_ip()), cfg.rl_ip_per_hour, 3600)


def enforce_public_read_rate_limits() -> None:
    """Found live (code audit): /v1/conditions and /v1/taxonomy/activities are
    public (no auth, reachable before signup/login) and had NO rate limit at
    all — completely unthrottled scraping/flooding.

    Deliberately NOT reusing enforce_preauth_rate_limits()/its Redis keys:
    that would share one bucket between these harmless reference-data reads
    and signup/login/password-reset, so a device merely loading the
    onboarding screen a few times could eat into the budget that's supposed
    to protect signup/login — a self-inflicted lockout, not a security fix.
    Separate "ref:" keys keep this an independent budget.
    """
    cfg = current_app.config["APP_CONFIG"]
    _incr_window(f"rl:device:ref:{_device_id()}", cfg.rl_device_per_hour, 3600)
    _incr_window(f"rl:ip:ref:{_client_ip()}", cfg.rl_ip_per_hour, 3600)


def enforce_user_rate_limit(user_id: str) -> None:
    cfg = current_app.config["APP_CONFIG"]
    _incr_window(rc.key_rl_user(user_id), cfg.rl_user_per_minute, 60)


def require_auth(fn: Callable) -> Callable:
    """Verify signature, then check revocation, then rate-limit the user.

    Order matters: an invalid token must not consume a rate-limit slot keyed on a
    user id we have not yet authenticated.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise Unauthorized("Missing bearer token")
        raw = header[7:].strip()

        cfg = current_app.config["APP_CONFIG"]
        claims = tk.decode_access_token(cfg, raw)   # 2.1 stateless verification
        tk.assert_not_revoked(claims)               # 2.2 single Redis round trip

        g.user_id = claims["sub"]
        g.access_claims = claims
        g.device_id = _device_id()

        enforce_user_rate_limit(g.user_id)
        return fn(*args, **kwargs)

    return wrapper


def require_staff(fn: Callable) -> Callable:
    """1.7 — staff-only routes. Must sit *inside* @require_auth (below it in
    the decorator stack) since it needs g.user_id already set.

    A DB lookup per request is deliberate, not an oversight: the flag is
    never in the JWT, so revoking staff access takes effect on the very
    next request rather than waiting for every outstanding token to expire.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from app.auth.models import User
        from app.platform.db import session_scope

        with session_scope() as session:
            user = session.get(User, g.user_id)
            if user is None or not user.is_staff:
                raise Forbidden("Staff access required.")
        return fn(*args, **kwargs)

    return wrapper
