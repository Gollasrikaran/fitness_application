import pytest
from app.platform.db import session_scope
from app.platform.errors import QuotaExhausted, RateLimited
from app.rag import service as rag_service
from app.rag import vectorstore
from app.voice import service

def test_voice_extraction_clean(make_user, monkeypatch):
    user = make_user()
    def fake_chat_complete(*a, **k):
        return '[{"activity_type": "walk", "activity_name": null, "is_custom": false, "set_amounts": [2], "unit": "km", "duration_minutes": 15}]'
    monkeypatch.setattr(service, "chat_complete", fake_chat_complete)

    with session_scope() as s:
        result = service.extract_activities(s, user["user_id"], "I walked 2km in 15 minutes", openrouter_api_key="unused")
        assert len(result["entries"]) == 1
        assert result["entries"][0]["activity_type"] == "walk"

def test_voice_extraction_multi(make_user, monkeypatch):
    user = make_user()
    def fake_chat_complete(*a, **k):
        return '[{"activity_type": "glute_bridge", "activity_name": null, "is_custom": false, "set_amounts": [20, 15, 12], "unit": "count", "duration_minutes": null}, {"activity_type": null, "activity_name": "pushups", "is_custom": true, "set_amounts": [10, 10], "unit": "count", "duration_minutes": null}]'
    monkeypatch.setattr(service, "chat_complete", fake_chat_complete)

    with session_scope() as s:
        result = service.extract_activities(s, user["user_id"], "20 then 15 then 12 glute bridges and 10 then 10 pushups", openrouter_api_key="unused")
        assert len(result["entries"]) == 2

def test_voice_extraction_quota_exhaustion(make_user, monkeypatch):
    user = make_user()
    with session_scope() as s:
        for _ in range(rag_service.VOICE_DAILY_LIMIT):
            rag_service._consume_quota(s, user["user_id"], quota_type=rag_service.VOICE_QUOTA_TYPE, limit=rag_service.VOICE_DAILY_LIMIT)
    
    with session_scope() as s:
        with pytest.raises(QuotaExhausted):
            service.extract_activities(s, user["user_id"], "test", openrouter_api_key="unused")

def test_voice_extraction_refund(make_user, monkeypatch):
    user = make_user()
    def fake_chat_complete(*a, **k):
        raise vectorstore.UpstreamUnavailable("simulated")
    monkeypatch.setattr(service, "chat_complete", fake_chat_complete)
    
    with session_scope() as s:
        with pytest.raises(RateLimited):
            service.extract_activities(s, user["user_id"], "test", openrouter_api_key="unused")
    
    # Check refund by ensuring we can consume VOICE_DAILY_LIMIT times
    with session_scope() as s:
        for _ in range(rag_service.VOICE_DAILY_LIMIT):
            assert rag_service._consume_quota(s, user["user_id"], quota_type=rag_service.VOICE_QUOTA_TYPE, limit=rag_service.VOICE_DAILY_LIMIT)
        assert not rag_service._consume_quota(s, user["user_id"], quota_type=rag_service.VOICE_QUOTA_TYPE, limit=rag_service.VOICE_DAILY_LIMIT)

def test_voice_extraction_garbage_response(make_user, monkeypatch):
    user = make_user()
    def fake_chat_complete(*a, **k):
        return 'not json'
    monkeypatch.setattr(service, "chat_complete", fake_chat_complete)

    with session_scope() as s:
        result = service.extract_activities(s, user["user_id"], "test", openrouter_api_key="unused")
        assert result["entries"] == []

def test_voice_extraction_hallucinated_code(make_user, monkeypatch):
    user = make_user()
    def fake_chat_complete(*a, **k):
        return '[{"activity_type": "jog", "activity_name": null, "is_custom": false, "set_amounts": [2], "unit": "km", "duration_minutes": 15}]'
    monkeypatch.setattr(service, "chat_complete", fake_chat_complete)

    with session_scope() as s:
        result = service.extract_activities(s, user["user_id"], "jog 2km", openrouter_api_key="unused")
        assert len(result["entries"]) == 1
        assert result["entries"][0]["activity_type"] is None
        assert result["entries"][0]["is_custom"] is True
        assert result["entries"][0]["activity_name"] == "jog"
