"""Functional correctness for Module 5's non-answer-quality behavior: quota
atomicity (5.4), the referred-bucket gate (13.3b), and the condition
disambiguation round trip (5.6). These are the flows verified manually,
one-off, throughout development — this makes them repeatable.
"""
from app.platform.db import session_scope
from app.rag.service import DAILY_LIMIT, _consume_quota


def test_quota_blocks_after_daily_limit(make_user):
    """5.4 — the Nth+1 attempt past DAILY_LIMIT must be refused, atomically."""
    user = make_user(condition_codes=["gout"])
    with session_scope() as s:
        results = [_consume_quota(s, user["user_id"]) for _ in range(DAILY_LIMIT + 2)]
    assert results == [True] * DAILY_LIMIT + [False, False]


def test_referred_user_blocked_with_no_quota_spent(make_user, client):
    """13.3b — a refer-bucket condition gets the referral message and nothing
    else, and it must not cost a quota slot to be told that."""
    user = make_user(condition_codes=["heart_condition"])
    r = client.post(
        "/v1/rehab/query", json={"question": "can I go for a run"}, headers=user["headers"]
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["referred"] is True
    assert d["answer"] is None
    assert d["quota"]["remaining"] == DAILY_LIMIT


def test_condition_disambiguation_round_trip(make_user, client):
    """5.6 — a symptom description gets suggested condition options (costing no
    quota), and confirming one both records the condition AND answers the
    original question in the same round trip, for exactly one quota unit total.

    Note: this depends on the free classifier model matching "wrist hurts and
    tingles" to carpal_tunnel. It's not perfectly deterministic even at
    temperature=0 with a small free model — if this test flakes, that's a real
    signal about classifier reliability, not a broken test.
    """
    user = make_user(condition_codes=["none"])

    r1 = client.post(
        "/v1/rehab/query",
        json={"question": "my wrist hurts and tingles when I type for a while"},
        headers=user["headers"],
    )
    d1 = r1.get_json()
    assert d1["needs_condition_selection"] is True, d1
    assert d1["quota"]["used"] == 0

    opts = d1["condition_options"]
    r2 = client.post(
        "/v1/rehab/query",
        json={
            "question": opts["original_question"],
            "condition_confirmation": {"code": opts["matched_code"]},
        },
        headers=user["headers"],
    )
    d2 = r2.get_json()
    assert d2["needs_condition_selection"] is False
    assert d2["answer"] is not None
    assert d2["quota"]["used"] == 1

    profile = client.get("/v1/profile", headers=user["headers"]).get_json()
    codes = {c["code"] for c in profile["conditions"]}
    assert opts["matched_code"] in codes
