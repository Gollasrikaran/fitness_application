from flask import Blueprint, current_app, g, jsonify, request

from app.gateway.middleware import require_auth
from app.platform.db import session_scope
from app.platform.errors import ValidationError
from app.voice import service

bp = Blueprint("voice", __name__, url_prefix="/v1/voice")


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Expected a JSON object body.")
    return data


def _str_field(d: dict, key: str, default: str = "") -> str:
    value = d.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ValidationError(f"{key!r} must be a string.")
    return value.strip()


def _voice_config():
    cfg = current_app.config["APP_CONFIG"]
    if not cfg.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured; voice logging cannot run yet.")
    return cfg


@bp.post("/extract")
@require_auth
def extract():
    d = _body()
    transcript = _str_field(d, "transcript")
    cfg = _voice_config()
    with session_scope() as s:
        return jsonify(service.extract_activities(
            s, g.user_id, transcript, openrouter_api_key=cfg.openrouter_api_key,
        ))
