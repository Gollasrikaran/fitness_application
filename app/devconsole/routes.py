"""Development-only UI harness.

Two things live here, neither ships:
  /dev      raw API console (request/response log)
  /ui       the design mockups, plus a working auth screen in the same design

Registered only when FLASK_ENV != production. The product UI is a mobile app
(Module 11); the backend serves JSON exclusively.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, render_template, request, send_from_directory

bp = Blueprint("devconsole", __name__,
               template_folder="templates", static_folder="static")


@bp.before_request
def _require_devconsole_auth():
    """Independent auth layer (found live, code audit): the ONLY thing ever
    gating this whole blueprint was `if not cfg.is_production` in
    factory.py. Requiring FLASK_ENV to be set explicitly (config.py) closes
    "forgot to set it, silently defaulted to dev" — but "development" and
    "test" are both legitimate non-production values, so a deliberate or
    accidental FLASK_ENV=test on a reachable box (a staging URL, a preview
    deploy) would still leave this entire blueprint open with zero login of
    its own: /app is a full working clone of the mobile client wired to the
    real signup/login/refresh/logout endpoints, and /dev logs raw
    request/response bodies, tokens included.

    HTTP Basic Auth specifically because every route here is meant to be
    opened directly in a browser by typing a URL — a header/query-param
    token scheme would need custom tooling just to view a page; a browser
    handles a Basic Auth prompt natively.

    Fails CLOSED: if DEVCONSOLE_PASSWORD isn't configured, every request
    here is refused outright, not silently let through.
    """
    cfg = current_app.config["APP_CONFIG"]
    if not cfg.devconsole_password:
        abort(403, "devconsole is not configured for this environment (DEVCONSOLE_PASSWORD unset).")
    auth = request.authorization
    valid = (
        auth is not None
        and secrets.compare_digest(auth.username or "", cfg.devconsole_user)
        and secrets.compare_digest(auth.password or "", cfg.devconsole_password)
    )
    if not valid:
        return Response(
            "Authentication required.", 401,
            {"WWW-Authenticate": 'Basic realm="devconsole"'},
        )


@bp.after_request
def _no_cache(response):
    """This is a single-file dev SPA edited constantly during this project -
    a stale browser cache silently serving yesterday's JS (while the server
    is already running today's) has repeatedly looked like a real app bug.
    Never worth caching in dev; forces every load to be the current file.
    """
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


MOCKUPS = Path(__file__).parent / "static" / "mockups"

PAGES = {
    "1": ("page1.html", "Onboarding"),
    "2": ("page2.html", "Activity Logging"),
    "3": ("page3.html", "Rehab & Pain Chat"),
    "4": ("page4.html", "Video Library"),
    "5": ("page5.html", "Settings"),
}


@bp.get("/app")
def app_ui():
    """The application itself, wired to the real API."""
    return render_template("app.html")


@bp.get("/dev")
def console():
    return render_template("console.html")


@bp.get("/ui")
def ui_index():
    available = {k: (f, t, (MOCKUPS / f).exists()) for k, (f, t) in PAGES.items()}
    return render_template("ui_index.html", pages=available)


@bp.get("/ui/auth")
def ui_auth():
    """Signup / login in the mockups' design language.

    Deliberately not one of the five: the mockups have no auth screen at all,
    so there is nothing to reproduce here — this fills the gap.
    """
    return render_template("ui_auth.html")


@bp.get("/ui/<page>")
def ui_page(page: str):
    if page not in PAGES:
        abort(404)
    filename = PAGES[page][0]
    if not (MOCKUPS / filename).exists():
        abort(404)
    return send_from_directory(MOCKUPS, filename)
