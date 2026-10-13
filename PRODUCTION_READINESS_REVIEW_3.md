# Production Readiness Review #3 — from scratch

**Date:** 2026-08-31
**New this round:** the test suite was **actually executed** for the first time (a
local Postgres exists, so these integration tests can run, not just collect).

---

## Test results — real, not theoretical

| Run | Result |
|---|---|
| Auth / profile / gateway / mailer / devconsole | **60 passed** |
| Progression engine (6 suites) | **61 passed** |
| RAG safety / confirmations / revert / quota | **26 passed** |
| **Full suite** (excl. 4 heaviest live-LLM suites) | **201 passed, 1 failed** |

The single failure — `test_activity_recall.py::test_chat_endpoint_handles_the_originally_reported_multi_day_question`
— **failed identically before any of this round's changes**. It is model-dependent
(the LLM returned its "no verified information" fallback), i.e. pre-existing and
flaky, not a regression.

Running them caught a real defect that reading the code did not. That is the headline
of this round.

---

## Defects found in MY round-2 fixes (all corrected)

### 1. The lockout "fix" was a security regression — reverted
I had claimed a sustained attacker could renew the lockout window forever. **That was
wrong.** The `RateLimited` raise happens *before* the increment block, so during a
lockout that code is never reached and the TTL could never renew — the original code
was already correct and self-clearing.

My change made it strictly weaker: setting the TTL only on the first failure meant an
attacker pacing one guess every ~12 minutes let the key expire mid-sequence and
**never tripped the threshold at all**. A cumulative lockout became a 5-guesses-per-hour
rate limiter.

**Reverted.** While there, fixed a real pre-existing bug it exposed: `Retry-After`
reported a constant 30s while the account was actually locked for up to an hour.

### 2. The revert safety-gate broke the feature for most users — corrected
My round-2 gate demanded an exercise be in the *safe* list. But the program admits
anything not marked `avoid` — `modify` exercises are legitimately on a dashboard.

Measured against the shipped grid: a **`sprain_strain` user has 11 activities rated
`modify` and zero `avoid`** — the program allows all 12, my gate allowed **1**. "Bring
these back?" would have refused everything except Walking.

**Corrected to "not avoided"** — for the revert path only.

### 3. …but the *other* confirmation path was right as it was — restored
Changing `_confirm_program_update` the same way **broke a test that documents the
safe-only rule as deliberate**. The two paths genuinely differ:

- `_confirm_program_update` validates a **client-supplied** list against what the chat
  was ever allowed to name → safe-only is correct, and is a real security control
- `_confirm_revert` restores the user's **own previously-active** entries → "not
  avoided" is correct

I had flattened a deliberate distinction. Restored, with the reasoning written down so
the next person doesn't repeat it. **The test suite caught this; code review did not.**

### 4. Quota marker — two defects fixed
- The redeem-side Redis call was unwrapped: an outage would 500 instead of falling back
  to charging. Now wrapped, failing toward charging.
- A failure on the confirmation path refunded a slot **that request never charged**,
  clawing back the earlier turn's payment — a free question per upstream hiccup.

### 5. Reaper retention was mismatched with 10-year sessions — fixed
30-day retention against 3650-day tokens meant an attacker need only *wait a month*:
replaying a stolen token then returns a plain 401 instead of triggering theft
detection. Raised to 365 days, with the tradeoff documented.

### 6. `JWT_KEY_PREVIOUS` validation was in the wrong place — fixed
The check sat *inside* `if prev_kid and prev_key`, so a half-configured rotation was
silently ignored — which mass-invalidates every session holding a token signed with
that key. Now fails fast, and also rejects `prev_kid == current_kid` (which would
overwrite the current secret).

---

## Also fixed: four crash paths a real user could hit

| Bug | Effect |
|---|---|
| `source` never validated | `{"source":"web"}` → uncaught IntegrityError → **500**, and in a batch it discarded *every* entry. An offline-replay client would retry the doomed batch forever. |
| Huge `amount` | `float(10**400)` raises `OverflowError`, not caught → **500** |
| Non-string `question` | `{"question": 123}` → `AttributeError` → **500** |
| Chat before onboarding | No profile row → `AttributeError` → **500**, *after* the quota slot was already committed. The user paid for the crash. |

---

## Blockers — unchanged from review #2

1. **Account deletion still deletes nothing** — no purge job; health conversations
   retained indefinitely. Worse than previously stated: because the soft-deleted row
   keeps the UNIQUE email, the user **can never re-register with their own address**,
   and reset issues no token for an inactive user. Permanently bricked.
2. **No scheduled process exists** — `Procfile` has only `web:`. The weekly
   progression engine and everything downstream of it (escalation) never run in
   production. `progression_history` on the live DB: **0 rows**.
3. **& 4. The chatbot can still starve the app** — `--workers 1 --threads 4`, no
   per-request deadline, worst-case chain ~536s vs a 300s timeout.

---

## Capacity — unchanged, re-confirmed

| | |
|---|---|
| Hard concurrency ceiling | **4 simultaneous requests, app-wide** |
| Concurrent chatbot users | **4 saturates everything**; safe ceiling 2 |
| Chat throughput | ~8/min, ~240/hr sustainable |
| Dashboard load | ~15 DB round trips → **~5.6s** at current cross-region latency |
| Realistic DAU | **~300–800** (→ ~5,000–8,000 if the DB is colocated) |
| First bottleneck | Cross-region DB latency × chatty endpoints × 4 threads |

---

## Frontend — safe to host, still not committed

Verdict unchanged: **no attacker-facing blocker**. Latest edits verified correct
(`escapeHtml` on EMAIL doesn't mangle the avatar initial; `delAccount`'s success path
still clears state and navigates).

Still to do before deploying: **commit `frontend/` (it remains untracked)**, set
`VITE_API_URL` on Vercel, set Root Directory to `frontend`, set `CORS_ORIGINS` on
Railway, and don't upload the local `dist/` (it has `127.0.0.1:5057` baked in).

---

## Known-open, not fixed this round

- Safety backstop suppresses valid answers by bare substring match (the word "walking"
  in ordinary advice can replace an entire answer)
- Medication filter misses `prednisone`, `methotrexate`, `duloxetine`, "steroid injection"
- `program_confirmation` suspends every entry not in its list — an offer that reads as
  additive is destructive, and undocumented
- A23 reps fast-track (+193% week one) — skipped by your instruction
- `progression_series` bound can truncate charts for escalation-heavy accounts
- `errors.py` still misses availability errors that subclass `ResponseError`
  (`OutOfMemoryError`, failover errors)
- Signup leaks account existence (409 vs 201)
- `/v1/conditions`, `/v1/taxonomy/activities` unauthenticated *and* unrate-limited
- API_REFERENCE drift (`limit: 15` vs actual 5; escalation quota; undocumented fields)

---

## Honest assessment of this process

Three rounds, and **every round of fixes introduced new defects** — including this one
(I introduced two, caught both). The pattern is consistent enough to be worth stating:
changes to this codebase are not safe without the test suite, and the test suite was
never being run.

The single highest-value thing you could do is **make these tests runnable in CI**.
They caught a deliberate-design regression that two independent code audits missed.
