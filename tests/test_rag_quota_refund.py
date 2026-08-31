"""Regression tests for the third-pass code audit's CRITICAL finding: the
message-quota counter must be durably committed the instant it's consumed,
and durably refunded the instant an infra failure earns the user their slot
back — independent of whatever the rest of the request does afterward.

Before this fix, the whole request ran in one transaction that rolled back
on any uncaught exception, which could silently discard the just-applied
_consume_quota increment while the (real, billed) LLM call had already
happened — or, after committing the increment early, could just as easily
discard the _refund_quota decrement instead. Both directions are tested
here with a mocked vectorstore so no real OpenRouter call is made.
"""
import pytest

from app.platform.db import session_scope
from app.platform.errors import QuotaExhausted, RateLimited
from app.progression import analysis as progression_analysis
from app.rag import service as rag_service
from app.rag import vectorstore

FAKE_CHUNK = {
    "chunk_id": 1, "source_note": "test", "url": "", "text": "some retrieved text",
    "condition_code": "gout", "similarity": 0.9,
}
ACTIVITY = "glute_bridge"


def test_response_truncated_refund_is_durable(make_user, monkeypatch):
    """A truncated LLM reply (ResponseTruncated) must both (a) not crash
    uncaught, and (b) leave the user's quota exactly where it was before the
    attempt — not consumed, and not double-refunded."""
    user = make_user(condition_codes=["gout"])
    monkeypatch.setattr(vectorstore, "retrieve_chunks", lambda *a, **k: [FAKE_CHUNK])

    def fake_chat_complete(*a, **k):
        raise vectorstore.ResponseTruncated("simulated repetition-loop truncation")
    monkeypatch.setattr(vectorstore, "chat_complete", fake_chat_complete)

    with session_scope() as s:
        before = rag_service.remaining_quota(s, user["user_id"])["remaining"]

    with session_scope() as s:
        with pytest.raises(RateLimited):
            rag_service.answer_query(
                s, user["user_id"], "does turmeric help with gout pain",
                rag_db_url="unused", openrouter_api_key="unused",
            )

    with session_scope() as s:
        after = rag_service.remaining_quota(s, user["user_id"])["remaining"]

    assert after == before


def test_nonretryable_runtime_error_also_refunds(make_user, monkeypatch):
    """The same RuntimeError base class covers a non-retryable upstream
    status (e.g. a bad request to the chat API), not just the two named
    subclasses — must degrade the same way, not crash."""
    user = make_user(condition_codes=["gout"])
    monkeypatch.setattr(vectorstore, "retrieve_chunks", lambda *a, **k: [FAKE_CHUNK])

    def fake_chat_complete(*a, **k):
        raise RuntimeError("chat_complete failed: 422 simulated bad request")
    monkeypatch.setattr(vectorstore, "chat_complete", fake_chat_complete)

    with session_scope() as s:
        before = rag_service.remaining_quota(s, user["user_id"])["remaining"]

    with session_scope() as s:
        with pytest.raises(RateLimited):
            rag_service.answer_query(
                s, user["user_id"], "does turmeric help with gout pain",
                rag_db_url="unused", openrouter_api_key="unused",
            )

    with session_scope() as s:
        after = rag_service.remaining_quota(s, user["user_id"])["remaining"]

    assert after == before


def test_non_string_condition_confirmation_code_returns_422(make_user, client):
    """Found live (third-pass code audit): a non-string, unhashable `code`
    (a list) reached `code not in valid_codes` in service.py and raised an
    uncaught TypeError instead of a clean 422."""
    user = make_user(condition_codes=["none"])
    r = client.post(
        "/v1/rehab/query",
        json={"question": "test", "condition_confirmation": {"code": ["gout"]}},
        headers=user["headers"],
    )
    assert r.status_code == 422


def test_non_string_escalation_activity_type_returns_422(make_user, client):
    """Same bug class: a non-string activity_type survived `(... or "").strip()`
    in service.py and raised an uncaught AttributeError instead of a clean 422."""
    user = make_user(condition_codes=["none"])
    r = client.post(
        "/v1/rehab/query",
        json={"escalation_confirmation": {"activity_type": ["glute_bridge"], "confirmed": True}},
        headers=user["headers"],
    )
    assert r.status_code == 422


def test_escalation_quota_is_a_separate_bucket_from_the_message_quota(make_user):
    """Found live (third-pass code audit): escalation_confirmation had NO cap
    of its own, so a client could replay confirmed:true indefinitely for
    unlimited billed analyze_performance calls. Its new cap must be a
    separate counter — it must not eat into, or be confused with, the
    regular 5-message DAILY_LIMIT."""
    user = make_user()
    with session_scope() as s:
        results = [
            rag_service._consume_quota(
                s, user["user_id"],
                quota_type=rag_service.ESCALATION_QUOTA_TYPE, limit=rag_service.ESCALATION_DAILY_LIMIT,
            )
            for _ in range(rag_service.ESCALATION_DAILY_LIMIT + 2)
        ]
    assert results == [True] * rag_service.ESCALATION_DAILY_LIMIT + [False, False]

    with session_scope() as s:
        assert rag_service.remaining_quota(s, user["user_id"])["remaining"] == rag_service.DAILY_LIMIT


def test_escalation_confirmation_exhausted_returns_429_before_any_llm_call(make_user, monkeypatch):
    """The cap must be enforced BEFORE analyze_performance (the billed call)
    is ever reached, not just eventually reflected somewhere."""
    user = make_user()

    def fail_if_called(*a, **k):
        raise AssertionError(
            "analyze_performance must not be called once the escalation quota is exhausted")
    monkeypatch.setattr(progression_analysis, "analyze_performance", fail_if_called)

    with session_scope() as s:
        for _ in range(rag_service.ESCALATION_DAILY_LIMIT):
            assert rag_service._consume_quota(
                s, user["user_id"],
                quota_type=rag_service.ESCALATION_QUOTA_TYPE, limit=rag_service.ESCALATION_DAILY_LIMIT,
            )

    with session_scope() as s:
        with pytest.raises(QuotaExhausted):
            rag_service._confirm_escalation(
                s, user["user_id"], {"activity_type": ACTIVITY, "confirmed": True},
                openrouter_api_key="unused",
            )
