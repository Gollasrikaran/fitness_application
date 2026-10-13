# Production Readiness Review #2 — post-fix

**Date:** 2026-08-31
**Scope:** Everything — the 21 earlier fixes re-verified, the fixes' own regressions
hunted, and the whole remaining surface re-audited. Five parallel deep-dives plus
live testing against a running instance.

---

## HEADLINE

**Still not production ready — 4 blockers.** But the picture changed materially:
this pass found and fixed **the single most dangerous bug in the codebase**, which
neither the first review nor the fix round had caught.

### The bug that mattered most

For a user with **more than one condition**, the chatbot and the program disagreed
about safety, and the chatbot was wrong in the unsafe direction.

- The program blocks an exercise if **any** of your conditions marks it `avoid`
- The chatbot approved an exercise if **any** of your conditions marks it `safe`

Real, shipped data: `hamstring_stretch` is `safe` for gout and **`avoid` for
herniated disc** (*"loaded flexed-spine position"*). So a user with **gout + a
herniated disc** had it correctly removed from their program — while the chatbot
was free to recommend that exact stretch to them. Worse, one tap on "add these to my
program" re-validated against the same faulty rule and wrote it back onto their
dashboard, bypassing the entire override-consent flow that the manual add path
enforces.

For a rehab app, recommending the one movement your own safety grid says to avoid
for that user's spine is the worst class of bug available. **Fixed and verified
live** — `avoid` now wins everywhere, for every condition a user has.

*Two independent audits found this separately; my own earlier `_confirm_revert` fix
had inherited the same flawed helper.*

---

## Fixes I got wrong the first time (found and corrected this pass)

| What | What went wrong | Now |
|---|---|---|
| **Quota exemption** | My fix let the client *assert* a free continuation — `condition_confirmation: {}` skipped quota entirely and returned a full billed answer. **Unlimited free LLM calls per account.** Strictly worse than the double-charge it replaced. | Server now proves it: a short-lived Redis marker is set only when the server actually asked "which condition?", and redeemed exactly once. **Both paths verified live** — exploit charged 5→4; legitimate suggestion→confirm cost exactly 1 slot total. |
| **Refresh-token reaper** | Two of my own changes collided: I set sessions to 3650 days, which made the reaper's `expires_at < now()` match nothing. **Permanent no-op** — the unbounded growth it existed to fix was unfixed. | Targets *dead* rows (rotated/revoked) past a 30-day retention, which is where the growth actually is. Retention keeps token-replay theft detection intact. |
| **Login lockout** | I used `EXPIRE ... NX`, which needs **Redis ≥ 7.0**. On Redis 6 that raises, and through the pipeline **every failed login becomes a 500**. Nothing pins a Redis version. | Rewritten as INCR + read TTL + conditional EXPIRE — the same shape the rate limiter already uses. Version-agnostic. |
| **Redis error handling** | I caught `RedisError`, the base of *every* redis-py exception — genuine bugs (WRONGTYPE, malformed commands) silently stopped being recorded as issues. | Narrowed to the connectivity subset only. |
| **`_confirm_revert` safety check** | Used the flawed "safe for any condition" helper — so my "safety re-check" could itself restore an avoid-verdict exercise. | Fixed with the corrected rule. |
| **Admin reset script** | With `FLASK_ENV=development` against the prod DB (very plausible), it silently used in-memory Redis — password changed, but the user stayed locked out and old sessions stayed valid. | Now requires real Redis; refuses to half-succeed. |
| **Batch cap** | 50 was sized by intuition. At this deployment's real DB latency that's a ~50s request pinning one of only four threads. | Lowered to 15 (~15s worst case). |

**Verified correct, no regression:** the savepoint dedupe (confirmed empirically —
batch survivors kept, session still usable after the caught error), the referral
soft-suspend (every consumer checked — the weekly job and dashboard both filter
correctly), the memory cap (keeps the *newest* 30, oldest-first ordering preserved),
the `no-device:<ip>` bucket, and all five frontend edits.

---

## Also fixed this pass

- **Weekly progression could apply twice in one night.** `applied_at` is stored UTC
  but compared against an IST date, so between **00:00–05:29 IST** the guard missed
  and a re-run stacked a second week of progression. Now compares in IST. *(This was
  on the original list; I missed it in the fix round.)*
- **Unbounded query on the hottest endpoint.** `progression_series` loaded *every*
  history row ever, on every dashboard open, to render the last 12 weeks. Now bounded.
- **`video_url` returned `""` instead of `null`** on every suggestion card, against
  the documented contract — clients checking `!== null` rendered a dead play button
  on every exercise.
- **`JWT_KEY_PREVIOUS` had no length floor** while `JWT_KEY_CURRENT` did — rotation
  could quietly reintroduce a forgeable key.
- **Frontend:** the user's own email is now escaped before `innerHTML` (backend
  accepts `<img src=x onerror=…>@a.b` as an address), and **`delAccount` no longer
  logs you out when deletion failed** — it used to swallow the error and tell you the
  account was gone while it was still live.

---

## BLOCKERS — still open

### 1. Account deletion still deletes nothing
Unchanged from review #1, and confirmed again: only `deleted_at` is set, cascades
never fire, **no purge job exists**, and `deletion_requests.purge_after` is written
but never read. Health conversations (`rehab_chat_log`, `rehab_memory`), activity
logs, profile, conditions and progression history are all retained indefinitely,
identity-linked. The API still replies `"deletion_scheduled"`.

### 2. The weekly progression job has no way to run in production — **new finding**
The `Procfile` defines **only** `web:`. `railway.json` has no cron schedule. There is
no worker or scheduled process anywhere in the deployment config.

So `run_weekly_progression.py` — the entire RLM progression engine — **never runs**.
And because escalation eligibility requires `ProgressionHistory` rows that only that
job writes, the chat's escalation feature is silently dead too. Confirmed against the
live database: `progression_history` has **0 rows**.

Two features you built are inert in production, failing silently.

### 3 & 4. The chatbot can still take down the whole app
Unchanged, and re-measured. `--workers 1 --threads 4`, no per-request deadline
anywhere. Worst-case chain on the performance path is **~536s** against a 300s
timeout. **Four simultaneous chat users saturate the entire application** — login,
dashboard and logging all queue behind them.

---

## Capacity — worst case, per service

*Measured, not assumed: this deployment runs Railway (Singapore) against Supabase
(Tokyo), ~350ms per DB round trip — `/v1/conditions` takes 1.24s vs 0.32s for a
no-DB endpoint.*

| Service | Number |
|---|---|
| **Hard concurrency ceiling** | **4 simultaneous requests, app-wide.** Request 5 queues with no deadline. |
| **Chatbot — concurrent** | **4 saturates everything.** Safe design ceiling: **2**. |
| **Chatbot — throughput** | ~8 msg/min, ~480/hr theoretical; **~240/hr sustainable** |
| **Chatbot — worst case single message** | 536s (performance path, 6 LLM calls × 90s worst) vs 300s timeout |
| **RAG retrieval** | ~5–15ms of vector math, but **~0.7–1.0s of unpooled cross-region connect** per query. **No index on the embedding column** (HNSW is commented out) — fine at 834 chunks, degrades past ~10–20k |
| **RLM weekly job** | 1,000 users ≈ **25 min** at current latency (34s if colocated); 10,000 ≈ **4.2 hrs**. *Currently 0 min — it never runs.* |
| **RLM chat analysis** | +1–2 LLM calls when triggered (~15–30% of messages) |
| **Dashboard summary** | ~15 DB round trips → **5.6s per load**, ~0.7 req/s. (Colocated: ~28 req/s) |
| **Activity logging** | ~6 round trips → 2.4s, ~1.7 req/s |
| **Concurrent users, normal use** | **~10–15** before p95 exceeds 10s |
| **Realistic DAU** | **~300–800.** Colocating the database alone takes this to ~5,000–8,000 |
| **First bottleneck** | Cross-region DB latency × chatty endpoints × 4 threads |
| **Second bottleneck** | Deadline-less chat requests monopolizing those 4 threads |
| **Third** | Shared-NAT rate limiting: **30–100 students per campus IP** before mutual lockout |

---

## Frontend — **safe to host**

Independent verdict: **SAFE TO HOST — no attacker-facing blocker.** Nothing lets a
stranger attack another user.

Verified: all 27 inline handlers exposed on `window`, zero orphaned element lookups
in either direction, both fetch paths prefixed, all five asset paths routed through
`assetUrl()`, chat output escape-first, builds clean, **no SPA rewrites needed**.

**Before you deploy (config, not code):**
1. `frontend/` is **still untracked in git** — commit it, there's nothing to deploy from
2. Set `VITE_API_URL` in Vercel — if unset, the app silently ships same-origin and every screen shows "Not Found"
3. Set Root Directory = `frontend`
4. Set `CORS_ORIGINS` on Railway to the Vercel domain (it fails closed, empty by default)
5. Don't upload your local `dist/` — it has `127.0.0.1:5057` baked in

**Worth fixing soon:** `loadHome`/`loadVideos`/`loadProfile` still have no try/catch,
so a failed request leaves a blank screen with no message. Also `pwForgotMode` is now
dead code, and the `watch_url` link needs `rel="noopener noreferrer"`.

---

## Remaining risks, ranked

| Severity | Finding |
|---|---|
| High | **Safety backstop suppresses correct answers** — a bare substring match means the word "walking" in ordinary self-care advice replaces the whole answer with "I can't recommend Walking…" for any user whose grid doesn't mark walk `safe`. High-frequency false positive on exactly the advice this app exists to give. |
| High | **Medication filter false negatives**: `prednisone`, `methotrexate`, `duloxetine`, bare `"steroid injection"` all pass the filter. |
| High | **`program_confirmation` isn't tied to an offer** — a crafted request suspends every active entry not in its list, silently wiping a dashboard. Same class as the quota hole I closed; same fix pattern applies. |
| Medium | **A23 reps fast-track** (skipped by your instruction): beginner 2×5 → 2×15 (**+193%**) in week one; a single honest 2×100 log can drive 3×50. |
| Medium | **10-year sessions**: the absolute cap now never fires and there's no session-list/revoke endpoint — a lost-device token is good for a decade. Revocation itself is sound (it's in Postgres, not Redis). |
| Medium | Signup leaks account existence (409 vs 201) while login was carefully de-enumerated. |
| Medium | `/v1/conditions` and `/v1/taxonomy/activities` are unauthenticated **and** unrate-limited, both full-table scans. |
| Medium | `/v1/rehab/history` still unpaginated — up to 200 full exchanges, ~1.5 MB. |
| Low | Custom-exercise TOCTOU (duplicate names, 20-cap bypass); `list_catalogue` N+1; email validation is just `"@" in email`; admin reset doesn't invalidate outstanding reset tokens; API_REFERENCE drift (`limit: 15` vs actual 5). |

---

## Recommended order

1. **Add a scheduled process for the weekly job** — a second Railway service running
   `python scripts/run_weekly_progression.py` on a daily cron. Without it, two shipped
   features do nothing. *(Also schedule `cleanup_expired_refresh_tokens.py`.)*
2. **Colocate Railway and Supabase** — ~20× on every screen, config-only.
3. **Move the chatbot off the web threads** (or at minimum raise `--workers` above 1
   and add a real per-request deadline) — blockers 3 & 4.
4. **Write the deletion purge job** — blocker 1, and the most legally exposed item.
5. Tie `program_confirmation` to a server-issued offer, like the quota marker.
6. Fix the safety backstop's substring matching and the medication list.
7. Frontend try/catch, then commit `frontend/` and deploy.

---

## Verification performed

**Live, against a running instance:** quota bypass exploit (charged correctly),
legitimate suggestion→confirm flow (1 slot total), avoid-verdict exercise refused for
a gout+herniated-disc user, exercise-name rejection, batch cap, walk/running excluded
from videos, IST/UTC guard arithmetic, device-bucket isolation.

**Against the live database:** `alembic check` clean, 23-table inventory, RAG index
listing, `progression_history` row count (0 — proving the job has never run).

**Static:** all edited files compile, 231 tests still collect, frontend builds clean.

**Not done:** the test suite still cannot *run* — it needs a live Postgres, the
Supabase RAG database and real paid OpenRouter calls (`tests/conftest.py`). There is
still no automated safety net for any change.
