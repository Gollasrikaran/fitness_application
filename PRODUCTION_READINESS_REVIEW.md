# Production Readiness Review — ViTAinspire

**Date:** 2026-08-31
**Scope:** Full backend + the newly-extracted `frontend/`. Every feature, every
input/output path, plus worst-case capacity per service.
**Method:** Verified against the actual code and against the **live deployment**
(Railway + Supabase), not against the docs. Where a number is measured, it says so.

---

## VERDICT: **NOT production ready.**

Nine blockers. The architecture and code quality are genuinely good — the auth timing
defences, the safety-grid design, the progression guard rails and the audit trails are
better than most projects this size. What is missing is the **operational** layer:
account recovery, data deletion, and any protection against one slow chatbot request
taking down the whole app.

| Area | Verdict |
|---|---|
| Core CRUD (profile, logging, program, dashboard) | **Solid** — ship-quality with 3 fixable risks |
| Auth crypto & token design | **Strong** — genuinely well built |
| Auth operations (recovery, deletion) | **Broken** — 2 blockers |
| RAG chatbot | **Unsafe to expose** — can kill the app for everyone |
| RLM progression engine | **Good design, 2 real bugs** |
| Capacity | **~4 concurrent requests total.** Hard ceiling. |
| Frontend | **Not hostable as-is** — 2 blockers, both 5-minute fixes |
| Data layer | **1 blocker** — a live landmine under the RAG corpus |

---

## THE BLOCKERS (must fix before real users)

### 1. Password reset is 100% non-functional → users are permanently locked out
`app/platform/mailer.py:36-39` logs an ERROR and returns in production. The reset token
is deliberately **not** in that log line, so it is irretrievable even by an admin.
The crypto is correct (256-bit token, SHA-256 at rest, 1h expiry, single-use, revokes
all sessions) — it just never reaches anyone. There is no resend endpoint and no
alternate recovery path.

**Any user who forgets their password loses their account and all their data, forever.**

*(Email verification is equally dead but harmless — `email_verified_at` is written and
never read by anything.)*

### 2. "Delete account" does not delete anything
`app/auth/service.py:347` sets `deleted_at` and nothing else. Every FK is
`ondelete="CASCADE"`, but cascades never fire because the `users` row is never deleted —
**and no purge job exists anywhere** (`purge_after` is written, never read).

Retained indefinitely and still identity-linked: `activity_logs`, **`rehab_chat_log`
and `rehab_memory` (the user's health conversations)**, `progression_history`,
`user_profiles`, `user_conditions`, `custom_exercises`. The API replies
`"deletion_scheduled"`. Nothing is scheduled.

For a health app, this is the most legally exposed finding in this review.

### 3. One chatbot request can kill the app for every other user
Verified from the code:
- `chat_complete` = `timeout=25s` × `retries=3` + 5s/10s backoff = **90s worst case per LLM call** (`app/rag/vectorstore.py:180-259`)
- One chat message = **4-6 chat calls + 1-2 embeddings** (`app/rag/service.py:1527-1603`)
- Worst case chain = **424-540s**
- `Procfile` = `--workers 1 --threads 4 --timeout 300`

The chain exceeds the 300s timeout, so gunicorn **SIGKILLs the worker**. There is only
**one** worker, so killing it destroys all 4 threads — **three other users' in-flight
requests die with it**, whatever they were doing. There is no per-request deadline
anywhere in the RAG path.

### 4. Four simultaneous chat users saturate the entire application
Not a crash — the design ceiling. Each chat request holds one of the 4 threads for its
full wall-clock duration (15-45s typical). While 4 are in flight, **login, dashboard,
activity logging and `/healthz` all queue behind them.** Sustainable chat throughput:
**~5 messages/minute, ~320/hour, app-wide.**

### 5. One anonymous caller can block password reset for every user
`/verify-email` and both `/password-reset/*` routes never require `X-Device-Id`
(`app/auth/routes.py:136-181`), so `_device_id()` returns the literal string
`"unknown-device"` (`app/gateway/middleware.py:53`). **All such traffic app-wide shares
one rate-limit bucket** at 60/hour. 60 requests from any one person locks the flow for
everybody.

### 6. The next auto-generated migration will delete the entire RAG corpus
`alembic check` against the live database fails with `remove_table('rag_chunks')`.

`DATABASE_URL` and `RAG_DATABASE_URL` now point at the **same** Supabase database, which
holds 22 app tables **plus `rag_chunks` with 834 embedded chunks**. `rag_chunks` is
created by a script, not by Alembic, so Alembic sees it as foreign and will emit
`op.drop_table('rag_chunks')` on the next `--autogenerate`. Running that destroys the
whole corpus — every embedding that cost real API calls to produce — and the chatbot
silently degrades to "no relevant sources" on every question.

`app/platform/config.py:66-72` states the opposite intent: *"A separate Postgres …
by design — the vector store stays out of the primary datastore's blast radius."*
Two databases the design deliberately separated have been collapsed into one.

**Fix (5 min):** add an `include_object` filter in `migrations/env.py` so autogenerate
can never target `rag_chunks`. Or restore the two-database split.

### 7. Chat memory grows unbounded and eventually bricks the chatbot permanently
`_older_important_memory` (`app/rag/service.py:458-473`) has `.offset(5)` and **no
LIMIT** — it loads every memory row the user ever generated and injects all of them
into the prompt. At ~900 rows (about a year at the 5/day quota) the prompt exceeds the
model's context and **every subsequent message fails forever**. Cost per message climbs
linearly the whole way there.

### 8. Frontend ships with a pre-filled password and a fake-email fallback
- `frontend/index.html:25` — the password field is prefilled `value="a good long passphrase"`
- `frontend/src/main.js:148` — a blank email silently becomes `demo.<timestamp>@example.com`, creating a real account at an unreachable address

Both are dev-mockup conveniences. Neither can ship.

### 9. Frontend now *lies* about password reset
The original mockup carried a disclaimer — *"(Dev mode: this prototype has no mail
server yet…)"*. The extraction **dropped that line**, leaving a bare "Sent to your
email." (`frontend/index.html:366`) and the toast "If that email exists, a reset code
was sent." The flow is unwinnable and the UI now asserts the opposite. My port
introduced this — it should be restored or the flow removed until email works.

---

## MEASURED: production is running cross-region, and it costs ~1 second per page

I timed the **live** Railway deployment:

| Endpoint | Avg | Min | Max |
|---|---|---|---|
| `/healthz` (no DB) | 422 ms | 304 | 793 |
| `/v1/app/config` (no DB) | 316 ms | 269 | 378 |
| **`/v1/conditions` (hits DB)** | **1241 ms** | 1204 | 1283 |

Subtracting my own client latency (~316 ms baseline), **a trivial query costs ~900 ms**.

Cause: **Railway is in Singapore** (`x-railway-edge: sin1`, seen in your own earlier
response headers) while **Supabase is in Tokyo** (`aws-0-ap-northeast-1`). Every DB
round trip crosses that gap, and `pool_pre_ping=True` adds an extra `SELECT 1` to
*every* request.

**This is the highest-leverage fix in the whole review.** The dashboard makes ~13 DB
round trips — at this latency that is a **~4 second load**, versus ~130 ms if the two
were colocated. Moving the Railway service to a Tokyo region (or the Supabase project
to Singapore) is a config change worth roughly a **20× improvement** on every screen.

---

## CAPACITY — worst case, per service

*Assumptions: 1 container × 4 threads; chat mean 45 s; normal request mean 130 ms
**if colocated** (currently ~1 s, see above); active user ≈ 0.2 req/s.*

| Question | Answer |
|---|---|
| **Hard concurrency ceiling** | **4 simultaneous requests.** 1 worker × 4 threads. Request #5 queues indefinitely (no per-request deadline). |
| **Concurrent chatbot users** | **Exactly 4 — and that starves everything else.** Practical safe limit **2-3**. |
| **Chat throughput** | ~0.089 req/s = **5.3 messages/min = ~320/hour app-wide** |
| **Concurrent users, normal features** | ~100-150 **if colocated**. At today's cross-region latency, closer to **~15-30**. |
| **Realistic daily active users** | Comfortable to **~1,000-1,500**; degrades at 2,000-3,000; wall ~3,500 — *assuming colocation is fixed* |
| **DB pool** | 10 connections vs 4 threads — over-provisioned 2.5×, exhaustion structurally impossible. Fine. |
| **Supabase connections** | ≤20 of ~200 free-tier client slots = 10%. Fine. |
| **Redis (durable)** | 1,000 users ≈ 360 KB; 10,000 ≈ 3.6 MB. All keys TTL'd, no unbounded growth. Fine. |
| **Redis (cache)** | **Completely unused** — `rc.cache()` has zero call sites. You are paying for a second Redis that does nothing. |
| **Weekly progression job** | Separate cron process, no LLM calls. 1,000 users ≈ 45-90 s; 10,000 ≈ 7-14 min. Not a concern. |
| **LLM cost ceiling** | ~**50 billed OpenRouter calls per user per day**. Models are **paid, not free tier** (`openai/gpt-oss-20b` + `text-embedding-3-small`). |
| **First bottleneck** | The 4 threads, held by long RAG requests. Not CPU, RAM, DB or Redis — those have 3-25× headroom. |
| **Second bottleneck** | Shared-IP rate limiting (below) — hits before capacity does. |

### Students on shared campus WiFi will lock each other out

`RL_IP_PER_HOUR=200` applies to pre-auth routes **including `/refresh`**. With a 30-min
access token, every active user burns **~2 IP slots/hour just staying logged in**. On a
shared NAT (school/college WiFi), everyone shares one IP bucket:

> **~100 concurrent students, or ~200 one-off logins, per campus per hour** — then
> everyone gets 429 with `Retry-After` up to 3600 s.

A 300-student campus would trip this daily. Directly relevant given your student use case.

---

## Remaining findings by severity

### Fix before scale (RISK)

| # | Finding |
|---|---|
| A2 | **Victim lockout DoS** — lockout TTL refreshes on every failure, so ~4 failed logins/hour keeps a chosen account locked *permanently*. Comment claims it is "self-clearing"; under attack it is not. |
| A4 | **Revocation dies with Redis** — the JWT denylist and `tokens_valid_after` live only in Redis with no DB backstop. A Redis restart without persistence makes revoked/logged-out tokens valid again for up to 30 min. Verify AOF/RDB is on. |
| A8 | **Irreversible program loss** — selecting a refer-bucket condition *hard-deletes* the whole program (`profile/service.py:155`), the one place the codebase breaks its own soft-suspend rule. Reachable mid-chat, and unrecoverable even if the condition is removed. |
| A11 | **TOCTOU on `client_entry_id`** — SELECT-then-INSERT means a concurrent offline replay raises an uncaught `IntegrityError` → **500 instead of `duplicate: true`**. Exactly the flaky-mobile case it was built for. |
| A11 | No cap on batch `entries` — bounded only by the 1 MiB body limit (~20,000 entries in one transaction). |
| A22 | **Progression idempotency breaks 00:00-05:30 IST** — the guard compares a UTC timestamp against an IST date, so a re-run in that window **stacks a second week's increase**. |
| A23 | **Reps fast-track bypasses the ±20% cap** — week 1 can jump 5 → 14.7 reps (**+193%**) for a rehab beginner. Bounded only by the 30-rep ceiling, not by any per-week limit. |
| A21 | `_confirm_revert` never re-checks the safety grid — an exercise that became `avoid` after a condition change can be restored to active. |
| A19 | A symptom-sounding question costs **2 quota slots** of 5 (the suggestion turn, then the resend). |
| A16 | Custom exercise names are stored and returned **verbatim** — the entire XSS defence is client-side escaping. |
| B7 | `JWT_KEY_CURRENT` has **no minimum-length check** (unlike `SECRET_KEY`'s 32-char floor). A short HMAC secret is offline-brute-forceable → full auth bypass. One-line fix. |
| — | `refresh_tokens` grows forever — ~17k rows/user/year, no reaper job. |
| — | A Redis blip triggers an `AppIssue` **Postgres write per failed request** — a write storm exactly when things are already broken. |

### Cosmetic / honesty

- **Notifications do not exist.** No model, no route, no sender, no scheduler — the bell and page are a hardcoded empty array. The badge can only ever be 0.
- **Every video is a placeholder.** No video CSV exists; `seed_videos` inserts empty IDs for all 12 activities, each with a real-sounding title. The Video Library is empty content dressed as a library.
- **Voice FAB** — a prominent pulsing button whose only action is the toast "Voice logging isn't wired up yet".
- **RAG coverage is thin for some conditions** (measured): spinal stenosis 3 chunks, degenerative disc 5, spondylosis 5, hip arthritis 6, bursitis 7. Expect repetitive answers and frequent refusals for those users. Well covered: osteoporosis 49, rheumatoid arthritis 40, carpal tunnel 19.
- **Safety backstop false-positives**: `DOSAGE_PATTERN` suppresses an entire valid answer containing e.g. "500 ml of water"; "reconstruction" is an ordinary word. False-negatives too — "prednisone", "morphine", "total knee replacement" match no keyword.

### What is genuinely good

- **Timing-attack defence on login** — a dummy Argon2 hash always runs, *before* the lockout check, closing the second-order oracle. Deliberate and correct.
- **JWT handling** — `algorithms=["HS256"]` pinned, `kid` is a fixed-map lookup, `jti` required. No alg-confusion surface.
- **Argon2id** at t=3, m=64 MiB, p=4 — above OWASP's floor.
- **Refresh rotation** with `SELECT … FOR UPDATE`, absolute cap, device-bound grace, theft detection.
- **Escalation gate cannot be bypassed** — the server re-derives eligibility and ignores the client's requested percentage.
- **Quota is atomic** (`UPDATE … WHERE count < limit`) and lives in Postgres, so a Redis flush cannot reset it.
- **Timezone handling is correct** throughout activity logging, streaks and trends (`today_ist()` used consistently).
- **Safety grid re-checked** before program writes; soft-suspend never deletes.
- **No SQL injection surface** — all ORM or parameterised.

---

## FRONTEND — can you host it?

**Not yet. Two 5-minute fixes stand between you and yes** (blockers 8 and 9 above).

The port itself is clean — I diffed it against the original: **no element IDs lost, no
functions lost, zero orphaned `$("...")` lookups in either direction**, all 28 inline
`onclick` targets correctly exposed to `window`, both `fetch` calls prefixed with
`API_BASE`, and all five backend-relative asset paths routed through `assetUrl()`.
It builds clean and needs no SPA rewrite rules (there is no client-side routing).

| # | Item | Verdict |
|---|---|---|
| D2 | All 8 screens present and reachable | PASS |
| D3 | API wiring / asset URLs | PASS |
| D4 | Global handlers exposed | PASS |
| D5 | Token refresh + rotation | PASS (`RT` not nulled on logout — sloppy, self-corrects) |
| D6 | XSS | RISK — see below |
| D7 | Error handling | **FAIL** — see below |
| D8 | Responsiveness | PASS (voice FAB detaches from the column on desktop) |
| D9 | Vercel-deployable | RISK — `VITE_API_URL` fails *silently* if unset |
| D10 | Honesty | **BLOCKER** — password reset, notifications |

**D7 — error handling is the real weakness.** `loadHome`, `loadVideos`, `loadProfile`
and `openProfileEditor` have **no try/catch at all**, and `go()` fires them as floating
promises with no `.catch`. A 500 or a dropped connection leaves a **blank screen** with
no message. Worse: **`delAccount` swallows its failure** — a wrong password means the
account is *not* deleted, yet the UI clears storage and logs you out as though it
worked.

**D6 — XSS.** No user-controlled hole except one: `EMAIL` is rendered raw into
`innerHTML` (`main.js:1319,1321`), and backend email validation is only
`"@" in email` — so `<img src=x onerror=…>@a` is an accepted address. Self-XSS scope
only (your own localStorage), but it is a real path. The wider unescaped surface
(`caution` text, catalogue names, video instructions, condition names) is
operator/LLM-controlled rather than attacker-controlled — lower risk, but it is the
same class of bug this codebase already fixed once before.

**Deploy steps when you do host it:** set Root Directory = `frontend` on Vercel (no
`vercel.json` exists), set `VITE_API_URL` to the Railway URL, and set `CORS_ORIGINS`
on Railway to the Vercel domain — it fails closed and is empty by default.

---

## Recommended order of work

1. **Colocate Railway and Supabase** (config change, ~20× latency win on every screen)
2. **Wire an email provider** — unblocks account recovery (blocker 1)
3. **Guard `rag_chunks` in `migrations/env.py`** (blocker 6, 5 lines, defuses a live landmine)
4. **Frontend: remove the prefilled password + demo-email fallback, restore the reset disclaimer** (blockers 8, 9)
5. **Require `X-Device-Id` on the three unauthenticated routes** (blocker 5)
6. **Move `/v1/rehab/query` off the web threads** — async job + poll, or a separate service (blockers 3, 4). Until then, raise `--workers` above 1 so one dying worker cannot take three other users with it.
7. **Cap `_older_important_memory` with a LIMIT** (blocker 7, one line)
8. **Write a purge job for deleted accounts** (blocker 2)
9. Then the RISK list, starting with the progression IST/UTC bug and the reps +193% jump

---

## Appendix — verification coverage

231 tests collect with zero import errors, but per `tests/conftest.py:1-6` they are
**integration tests by design** — they need a live local Postgres, the live Supabase
RAG database, and **real paid OpenRouter calls**. They cannot run in CI without all of
that, which is why no CI exists. **There is currently no automated safety net for any
change.**

Live-deployment checks performed for this review: `alembic check` against production,
full table inventory (23 tables), RAG corpus coverage per supported condition, and
timed latency against the running Railway service.
