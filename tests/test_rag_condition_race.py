"""Regression test for a race found live (fourth-pass audit, cross-check for
regressions): _add_condition used to be an unguarded read-modify-write — it
read the user's existing condition list, appended one code, and wrote the
merged list back via complete_onboarding, with no locking. Two near-
simultaneous chat-confirmed condition additions (a double-tap, two devices)
could both read the same starting list and each add a DIFFERENT condition;
whichever complete_onboarding call committed last would silently win,
dropping the other one entirely.

Fixed by locking the user's profile row (SELECT ... FOR UPDATE) before
reading the existing list, serializing the two calls so the second one to
actually run reads the first one's already-merged list, not a stale one.
"""
import threading

from app.platform.db import session_scope
from app.rag.service import _add_condition


def test_two_concurrent_condition_additions_both_persist(make_user):
    user = make_user(condition_codes=["none"])
    codes_to_add = ["gout", "carpal_tunnel"]
    barrier = threading.Barrier(len(codes_to_add))
    errors = []

    def _add(code):
        try:
            barrier.wait(timeout=5)  # maximize the chance both calls overlap
            with session_scope() as s:
                _add_condition(s, user["user_id"], code)
        except Exception as exc:  # noqa: BLE001 — surfaced via `errors` below
            errors.append(exc)

    threads = [threading.Thread(target=_add, args=(code,)) for code in codes_to_add]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"unexpected error(s) in worker threads: {errors}"

    with session_scope() as s:
        from app.profile import service as profile_service
        profile = profile_service.profile_summary(s, user["user_id"])
        final_codes = {c["code"] for c in profile["conditions"]}

    assert set(codes_to_add) <= final_codes, (
        f"expected both {codes_to_add} to survive the race, got {sorted(final_codes)} — "
        "one condition addition was silently lost"
    )
