"""HTTP surface for Module 5 (5.1, 5.4) — /v1/rehab/query, /v1/rehab/quota."""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from app.gateway.middleware import require_auth
from app.platform.db import session_scope
from app.platform.errors import ValidationError
from app.rag import service

bp = Blueprint("rehab", __name__, url_prefix="/v1/rehab")


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Expected a JSON object body.")
    return data


def _rag_config():
    cfg = current_app.config["APP_CONFIG"]
    if not cfg.rag_database_url or not cfg.openrouter_api_key:
        # A real deploy decision (production hard-requiring this) hasn't been made
        # yet — see PART2 chat log — so this fails loudly per-request rather than
        # refusing to boot the whole app over a feature still being wired up. The
        # generic exception handler logs the real reason server-side and returns a
        # safe message to the client.
        raise RuntimeError(
            "RAG_DATABASE_URL / OPENROUTER_API_KEY are not configured; "
            "Module 5 cannot answer queries yet."
        )
    return cfg


@bp.get("/quota")
@require_auth
def quota():
    with session_scope() as s:
        return jsonify(service.remaining_quota(s, g.user_id))


@bp.post("/query")
@require_auth
def query():
    d = _body()
    cfg = _rag_config()
    confirmation = d.get("condition_confirmation")
    if confirmation is not None and not isinstance(confirmation, dict):
        raise ValidationError("condition_confirmation must be an object.")
    with session_scope() as s:
        return jsonify(service.answer_query(
            s, g.user_id, d.get("question") or "",
            rag_db_url=cfg.rag_database_url,
            openrouter_api_key=cfg.openrouter_api_key,
            condition_confirmation=confirmation,
        ))
