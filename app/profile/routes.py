"""HTTP surface for Modules 3, 4, 6, 13, 14."""
from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, g, jsonify, request

from app.gateway.middleware import require_auth, require_staff
from app.platform.db import session_scope
from app.platform.errors import ValidationError
from app.profile import service
from app.progression import service as progression_service

bp = Blueprint("core", __name__, url_prefix="/v1")


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Expected a JSON object body.")
    return data


def _str_field(d: dict, key: str, default: str = "") -> str:
    """Found live (code audit): every one of these fields used to go through
    `(d.get(key) or "").strip()` — fine for a missing/empty value, but a
    client sending a JSON number/list/object for a string field made `or`
    pass the truthy non-string value straight through, and `.strip()` on it
    raised an uncaught AttributeError (a 500, misclassified as a server
    crash) instead of a clean 422. Also rejects a JSON `null` explicitly
    sent as e.g. {"goal": null} the same way `or ""` used to."""
    value = d.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ValidationError(f"{key!r} must be a string.")
    return value.strip()


def _optional_str_field(d: dict, key: str) -> str | None:
    return _str_field(d, key) or None


def _float_field(d: dict, *keys: str, default: float = 0.0) -> float:
    """Found live (code audit): `float(e.get("amount") or ... or 0)` crashed
    with an uncaught TypeError if the client sent a list/object instead of a
    number for a logged amount."""
    value = default
    for key in keys:
        if d.get(key) is not None:
            value = d[key]
            break
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{keys[0]!r} must be a number.")


def _int_field(d: dict, key: str, default: int) -> int:
    value = d.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{key!r} must be an integer.")
    except OverflowError:
        # Found live (second-pass code audit): int(float('inf')) raises
        # OverflowError, not ValueError/TypeError — {"sets": Infinity} (JSON
        # accepts bare Infinity/NaN by default) crashed uncaught here,
        # the same bug class already fixed for `days` in
        # dashboard_activity_detail but missed on this call site.
        raise ValidationError(f"{key!r} must be a finite integer.")


def _list_field(d: dict, key: str) -> list[str]:
    """Found live (code audit): `d.get(key) or []` let a non-list truthy
    value (e.g. a JSON number) through to be iterated, raising an uncaught
    TypeError. It also didn't reject a bare STRING (e.g. "reps" for
    measurement_types), which is technically iterable — it silently iterated
    as individual characters, producing a confusing validation error instead
    of a clean type error.

    Found live (second-pass code audit): validating the outer container
    alone wasn't enough — every real caller (condition_codes,
    measurement_types) feeds this straight into `dict.fromkeys(...)` for
    dedup, which calls hash() on each element; a non-string element (a list
    or dict) raised an uncaught TypeError there instead of here. Every real
    use of this helper is a list of taxonomy/condition CODES, so requiring
    string elements is correct for all current call sites, not just a
    convenient restriction."""
    value = d.get(key) or []
    if not isinstance(value, list):
        raise ValidationError(f"{key!r} must be a list.")
    if not all(isinstance(item, str) for item in value):
        raise ValidationError(f"{key!r} must be a list of strings.")
    return value


@bp.get("/conditions")
def conditions():
    """Public: the client needs this to render onboarding before a profile exists."""
    with session_scope() as s:
        return jsonify({"conditions": service.list_conditions(s)})


@bp.get("/taxonomy/activities")
def activities():
    with session_scope() as s:
        return jsonify({"activities": service.list_activities(s)})


@bp.post("/profile/onboarding")
@require_auth
def onboarding():
    d = _body()
    with session_scope() as s:
        return jsonify(service.complete_onboarding(
            s, g.user_id,
            age=d.get("age"),
            goal=_str_field(d, "goal"),
            experience_band=_str_field(d, "experience_band"),
            condition_codes=_list_field(d, "condition_codes"),
            unit_preference=_str_field(d, "unit_preference", "km"),
        ))


@bp.get("/profile")
@require_auth
def profile():
    with session_scope() as s:
        return jsonify(service.profile_summary(s, g.user_id))


@bp.put("/profile")
@require_auth
def update_profile():
    """3.4 — edit age / goal / experience_band / unit_preference in any
    combination, without resubmitting conditions or rebuilding the program."""
    d = _body()
    # Found live (second-pass code audit): this route used to pass raw JSON
    # values straight through as `fields`, and service.update_profile does
    # `if goal not in GOALS` etc. directly on them — a non-string value
    # (e.g. {"goal": ["a"]}) makes `in` on a set call hash() on it, raising
    # an uncaught TypeError instead of a clean 422. Only string fields are
    # actually settable here, so route every present key through _str_field.
    fields = {}
    for key in ("goal", "experience_band", "unit_preference"):
        if key in d:
            fields[key] = _str_field(d, key)
    if "age" in d:
        fields["age"] = d["age"]
    with session_scope() as s:
        return jsonify(service.update_profile(s, g.user_id, fields=fields))


@bp.get("/program")
@require_auth
def program():
    with session_scope() as s:
        return jsonify({"program": service.get_program(s, g.user_id)})


@bp.get("/program/catalogue")
@require_auth
def program_catalogue():
    with session_scope() as s:
        return jsonify({"catalogue": service.list_catalogue(s, g.user_id)})


@bp.post("/program/entries")
@require_auth
def add_program_entry():
    d = _body()
    with session_scope() as s:
        return jsonify(service.add_program_entry(
            s, g.user_id, _str_field(d, "activity_type"),
            override_confirmed=bool(d.get("override_confirmed")),
        ))


@bp.delete("/program/entries/<activity_type>")
@require_auth
def remove_program_entry(activity_type: str):
    with session_scope() as s:
        return jsonify(service.remove_program_entry(s, g.user_id, activity_type))


@bp.get("/suggestions")
@require_auth
def suggestions():
    with session_scope() as s:
        return jsonify(service.suggestions_today(s, g.user_id))


@bp.post("/activities")
@require_auth
def log():
    d = _body()
    entries = d.get("entries") or [d]
    # Found live (second-pass code audit): a truthy non-list "entries"
    # (e.g. {"entries": 5}) reached `for e in entries:` unchecked and raised
    # an uncaught TypeError ("int object is not iterable") instead of a
    # clean 422.
    if not isinstance(entries, list):
        raise ValidationError("'entries' must be a list.")
    out = []
    with session_scope() as s:
        for e in entries:
            if not isinstance(e, dict):
                raise ValidationError("Each activity entry must be a JSON object.")
            out.append(service.log_activity(
                s, g.user_id,
                activity_type=_optional_str_field(e, "activity_type"),
                custom_exercise_id=_optional_str_field(e, "custom_exercise_id"),
                amount=_float_field(e, "amount", "quantity"),
                sets=_int_field(e, "sets", 1),
                unit=_optional_str_field(e, "unit"),
                source=_str_field(e, "source", "manual"),
                client_entry_id=_optional_str_field(e, "client_entry_id"),
            ))
        return jsonify({"logged": out, "streak": service.streak(s, g.user_id)}), 201


@bp.get("/custom-exercises")
@require_auth
def custom_exercises():
    """4.4 — a user's own tracking-only exercises. Never suggested, never programmed."""
    with session_scope() as s:
        return jsonify({"custom_exercises": service.list_custom_exercises(s, g.user_id)})


@bp.post("/custom-exercises")
@require_auth
def create_custom_exercise():
    d = _body()
    with session_scope() as s:
        result = service.create_custom_exercise(
            s, g.user_id,
            name=_str_field(d, "name"),
            measurement_types=_list_field(d, "measurement_types"),
        )
        return jsonify(result), 201


@bp.put("/custom-exercises/<exercise_id>")
@require_auth
def rename_custom_exercise(exercise_id: str):
    d = _body()
    with session_scope() as s:
        return jsonify(service.rename_custom_exercise(
            s, g.user_id, exercise_id, _str_field(d, "name")))


@bp.delete("/custom-exercises/<exercise_id>")
@require_auth
def delete_custom_exercise(exercise_id: str):
    with session_scope() as s:
        return jsonify(service.delete_custom_exercise(s, g.user_id, exercise_id))


@bp.get("/dashboard/trend")
@require_auth
def dashboard_trend():
    """4.3 — flexible trend window: ?days=15 or ?start=YYYY-MM-DD&end=YYYY-MM-DD."""
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    days_str = request.args.get("days")
    try:
        start_date = date.fromisoformat(start_str) if start_str else None
        end_date = date.fromisoformat(end_str) if end_str else None
        days = int(days_str) if days_str else None
    except ValueError:
        raise ValidationError("start/end must be YYYY-MM-DD; days must be an integer.")
    with session_scope() as s:
        return jsonify({"trend": service.trend(
            s, g.user_id, days=days, start_date=start_date, end_date=end_date)})


@bp.get("/dashboard/activity-detail")
@require_auth
def dashboard_activity_detail():
    """Itemized log entries (which exercise, how much) over a date range —
    what /dashboard/trend deliberately doesn't give (a per-day count only).
    Defaults to the last 7 days; ?days=1 for just today, or an explicit
    ?start=&end= range, same convention as /dashboard/trend."""
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    days_str = request.args.get("days")
    try:
        if start_str or end_str:
            if not (start_str and end_str):
                raise ValidationError("start and end must both be provided together.")
            start_date, end_date = date.fromisoformat(start_str), date.fromisoformat(end_str)
        else:
            days = int(days_str) if days_str else 7
            # Found live (code audit): an unbounded `days` value here (e.g.
            # ?days=1000000) overflowed Python's date range BEFORE this ever
            # reached service.activity_log_detail's own cap below — date
            # only supports years 1-9999, and OverflowError isn't a
            # ValueError, so the existing except clause didn't catch it
            # either. A trivial, reliable, single-request crash.
            if days < 1 or days > service.MAX_TREND_DAYS:
                raise ValidationError(f"days must be between 1 and {service.MAX_TREND_DAYS}.")
            end_date = service.today_ist()
            start_date = end_date - timedelta(days=days - 1)
    except ValueError:
        raise ValidationError("start/end must be YYYY-MM-DD; days must be an integer.")
    with session_scope() as s:
        return jsonify({"entries": service.activity_log_detail(
            s, g.user_id, start_date=start_date, end_date=end_date)})


@bp.get("/dashboard/summary")
@require_auth
def dashboard():
    with session_scope() as s:
        return jsonify({
            "streak": service.streak(s, g.user_id),
            "week": service.weekly_volume(s, g.user_id),
            "suggestions": service.suggestions_today(s, g.user_id),
            # RLM design doc §7 / Implementation plan Phase 6 — additive field,
            # empty list until the weekly job (or a confirmed escalation) has
            # actually run at least once for this user.
            "progression": progression_service.progression_series(s, g.user_id),
            "signup_date": service.signup_date(s, g.user_id).isoformat(),
        })


@bp.get("/videos")
@require_auth
def videos():
    with session_scope() as s:
        return jsonify(service.video_library(s, g.user_id))


@bp.put("/admin/videos/<activity_type>")
@require_auth
@require_staff
def curate_video(activity_type: str):
    """Admin curation (7.1) — paste one watched, approved YouTube URL.

    Staff-only (1.7): require_staff replaces the old is_production block
    now that a real staff role exists. Works the same in every
    environment - gated on who you are, not which environment is running.
    """
    d = _body()
    with session_scope() as s_:
        return jsonify(service.set_video(
            s_, activity_type,
            url_or_id=_str_field(d, "url"),
            title=_optional_str_field(d, "title"),
        ))
