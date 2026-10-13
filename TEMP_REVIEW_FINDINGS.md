# TEMP — pre-push review findings (delete after acting on it)

**Date:** 2026-09-01
**Scope:** every file reviewed from scratch by five independent passes, plus my own
live verification. Email is **not** counted as a blocker (accepted gap, manual admin
reset script is the stand-in).

---

## GO / NO-GO: **PUSH THE BACKEND — but do not open it to real users yet**

Reasoning: everything in the working tree is **strictly better than what is live on
Railway right now**. Production is still on `517f5b2`, which contains the
multi-condition safety bug, four 500-crash paths, and the `rag_chunks` migration
landmine — all fixed locally. Every *new* problem found in this round is
**pre-existing and already live**, so pushing does not introduce it. Holding the push
keeps the worse code in production for no benefit.

What must NOT happen yet is putting real users on it — see the blockers below.

---

## Fixed during this review

| # | Issue | Severity |
|---|---|---|
| 1 | **`handle_theft` self-deadlock** — `rotate_refresh_token` holds `SELECT … FOR UPDATE` on the presented row; `handle_theft` opened a *second* session whose `UPDATE … WHERE revoked_at IS NULL` targeted that same row. Session 2 blocked on session 1's lock while session 1 waited in Python for session 2. Postgres saw one waiter, so the deadlock detector never fired and nothing timed out — the request hung forever holding 2 of 10 pooled connections. **Five events (a changed `X-Device-Id` is enough) would take the API permanently offline.** Now uses the caller's session + explicit commit. | **BLOCKER** |
| 2 | **`.env.example` shipped `FLASK_ENV=development`** — pasting it into Railway (the obvious move) boots production with the hardcoded dev SECRET_KEY and dev JWT key, debug logging, the full route map at `/`, and the devconsole mounted at `/app`+`/dev` with a published password, logging raw tokens. Now carries a prominent warning. | **CRITICAL trap** |
| 3 | `.env.example` documented 30/180-day token lifetimes while the code defaults to 3650 — copying it would silently shorten every session. | MED |
| 4 | **`logs/` was not git-ignored** — a 1.1 MB log with 5,576 user-id UUIDs would have been committed. | MED |
| 5 | **`analysis.py` caught only 2 of 3 LLM failure types** — a bare `RuntimeError` (OpenRouter 402 out-of-credit, 400, or a retired model slug) escaped, giving a **500 on the escalation path after the quota slot was already charged and committed**. | HIGH |
| 6 | **Frontend: `go()` fired all loaders uncaught** — a failed `/v1/profile` left the user on an empty Settings screen **with no Log out and no Delete account button**, and no error message. | HIGH |
| 7 | **Frontend: bootstrap logged users out on any error** — opening the app during a Railway cold start silently signed them out and discarded a perfectly valid token. Now only a real 401 ends the session. | MED |
| 8 | Frontend: `doLogout` cleared `AT` but not `RT` (every other sign-out path clears both). | LOW |

---

## BLOCKERS still open (pre-existing — already live today)

### B1. One chat tap can wipe most of a user's program
`_named_approved_activities` decides an exercise was "suggested" purely because its
display name appears **anywhere** in the answer text — including inside a negation
("avoid the Seated Hamstring Stretch") and, worse, inside the safety backstop's own
replacement text, which lists *every* approved exercise. `_confirm_program_update`
then calls `set_program_to_activities`, which suspends **every active entry not in
that list**.

Concrete: a `sprain_strain` user has 12 active entries but only `Walking` is `safe`.
Any answer mentioning walking — or any answer the backstop replaces — produces the
chip. The button reads only "+ Add these to my program: Walking". One tap suspends 11
exercises and their earned progression.

### B2. Chat-confirmed escalation is replayable and compounds
No per-day cap on *applying* an escalation (only 10/day on requesting), and
`apply_escalation` has no same-day guard — that guard exists only in the weekly job.
Each application also writes an adherence snapshot that feeds its own future
eligibility. Ten taps in one afternoon: 5 reps → 30 reps, same day, for a rehab
beginner. The per-step guards never engage against repetition.

### B3. Deployment: nothing runs the migration or the seed loader
No release phase in `railway.json`, only `web:` in the `Procfile`. And `/healthz`
returns ok against an **empty** database, so **Railway reports a healthy deploy while
every real endpoint 500s**. `alembic upgrade head` and `python -m app.catalog.loader`
must be run manually. An empty `safety_grid` is the exact "absent row reads as safe"
failure the loader's own docstring warns about.

### B4. No scheduled process in production
Still only `web:`. The weekly progression engine, everything downstream of it
(escalation eligibility), and the refresh-token reaper never run. The only scheduler
is a Windows Task Scheduler script on a developer laptop with
`FLASK_ENV=development` hardcoded.

### B5. `CORS_ORIGINS` must be set before the frontend works
Production default is empty and CORS is only installed when non-empty. Deploy goes
green, `/healthz` passes, and every browser request is blocked. Silent, not a crash.

---

## HIGH, not fixed

- **The approved-exercise backstop destroys valid answers.** A bare substring test over 12 display names. `Running` is `modify` for 9 of 10 conditions, so any answer containing "running" in ordinary prose ("pain running down your leg") is discarded and replaced with "I can't recommend Running for your condition." Needs word-boundary + context matching.
- **A long walk breaks the streak, and the dashboard contradicts itself.** `plausible_max_total` for walk/run is 15 km, so a half marathon is flagged implausible. `streak` filters those out but `last_logged` and `done_today` don't — one payload returns `completed: true`, `count: 0`, and `streak: 0`.
- **One bad entry still discards the whole batch.** The `source` fix turned a 500 into a 422, but it's still a whole-batch failure with no index in the message, so an offline client can't drop the bad entry and retries forever.
- **`amount: 0.004` → 500.** Passes the Python `> 0` check, then `Numeric(10,2)` rounds it to `0.00` and the CHECK constraint fires as an uncaught IntegrityError.
- **Long email or `X-Device-Id` → 500.** `DataError` is not a subclass of the `IntegrityError` being caught; a 400-char email or a 129-char device id 500s on signup/login/refresh, writing an `AppIssue` row per attempt.
- **Two browser tabs can revoke every session.** The grace branch picks the newest un-rotated token for the device rather than one linked to the presented row, so two tabs refreshing together can cannibalize each other and trip theft detection 30s later — all sessions revoked, push tokens deleted, forced re-login everywhere, for a user who did nothing.
- **Lockout is a flat 1 hour, not the 30s it reports**, and is remotely triggerable against any known email (~40 accounts/hour per IP).
- **`app_issues` can store SQL with bound parameters** — `repr(exc)` on a SQLAlchemy error embeds emails, token hashes and password hashes, retained after account deletion. Set `hide_parameters=True` on the engine.
- **The rule-1 backstop only knows 12 exercise names.** The corpus is 84 orthopaedic topics full of exercises the grid has never rated ("prone press-ups", "pelvic tilt"). For anything outside the catalog, enforcement is prompt-only.

## MEDIUM / LOW (see the five review outputs for detail)
Marker consumed even when the turn fails (429 message then lies); three of four
confirmation flows have no proof-of-offer; activity-recall answers can be hundreds of
KB and poison the next five prompts; `signup_date` off by one for early-morning IST
signups; N+1 on `/v1/program/catalogue` (~6s at current cross-region latency);
check-then-write races on custom exercises and onboarding; `{"entries": []}` gives a
nonsense error; `data/conditions.csv:16` truncated by an unquoted comma;
`unit_preference` is write-only; `watch_url` unescaped into an `href` (staff-writable
→ stored XSS); missing favicon and no `noindex` on a health app.

---

## Verification

| Check | Result |
|---|---|
| Full test suite | **199 passed, 3 failed** |
| — failure 1 | `test_activity_recall` — pre-existing, model-dependent flake |
| — failures 2 & 3 | `test_progression_reps_ceiling` — **pre-existing date-dependent test bug, not a regression.** The tests seed logs at a hardcoded `date(2026, 8, 25)` but `apply_escalation` uses the real current date. They passed on Aug 31 and broke when the date rolled to Sept 1 mid-session. They will fail every day from now on until the seed date is made relative. |
| Compile | PASS |
| `alembic check` vs live DB | PASS |
| Frontend build | PASS |
| Secrets in commit | PASS — `.env.dev`, `.env.local`, `dist/`, `node_modules/`, `logs/` all ignored; no key patterns in any staged file |

---

## Round 2 — the 5 issues the user asked to solve (email/OTP excluded)

| # | Issue | Fix |
|---|---|---|
| 1 | Chat "add these" wipes the rest of the program | Turned out to be an intentional, tested "switch sport focus" feature (5 tests pin the replace-behavior) — not a bug to remove. Fixed what actually WAS a bug: the trigger misfired on the safety-correction message itself (which lists every approved exercise), so confirming a correction could reset the whole program. Now skipped whenever the backstop corrected the answer. Also switched to word-boundary matching (fewer false positives) and made the button text honest ("Switch my program to: X, Y (others paused, not deleted)") instead of promising "add". |
| 2 | "Get harder" button spammable | `apply_escalation` had no same-day guard — only the separate weekly job did. Added the identical check; a second confirm on the same exercise same day now gets a clear "already updated today" response instead of stacking. |
| 3 | Nothing sets up the DB on deploy | `Procfile` now runs `alembic upgrade head && python -m app.catalog.loader` before starting the server — both are safe to re-run every deploy (verified idempotent). `/healthz` now actually queries the database and returns 503 if it's empty or unreachable, instead of a static "ok" — Railway's own deploy health check will now catch this instead of reporting false-green. |
| 4 | Weekly job has no process on Railway | **Cannot fix from code** — this needs a Railway Cron Job created in their dashboard, and no repo file can express a second scheduled service without one direct edit to Railway's own config UI. Script itself is ready. See final message to user for the exact 5-minute setup steps. |
| 5 | CORS blocks the frontend | **Cannot fix from code** — this is a Railway environment variable that must be set in their dashboard (`CORS_ORIGINS=<vercel-url>`), not something in the repo. |

Test fallout from fix #1: `_enforce_approved_exercises_only`'s return signature changed
(now returns `(answer, was_corrected)`); 4 tests in `test_rag_exercise_backstop.py`
asserted the old bare-string return and were updated to match — same logic, confirmed
by re-running: 15/15 pass.

**Final verification:** 192 passed / 3 failed (same 3 pre-existing date-dependent
failures as every prior run — confirmed not caused by these changes). Frontend builds
clean. `/healthz` verified live against the seeded local database.

## Before pushing

1. **Do not commit the four review `.md` files** if this repo is public — they enumerate
   the app's own weaknesses. (`PRODUCTION_READINESS_REVIEW*.md`, this file.)
2. Set `CORS_ORIGINS` on Railway.
3. After deploy: run `alembic upgrade head`, then `python -m app.catalog.loader`, then
   verify a real endpoint — **not** `/healthz`, which passes on an empty database.
