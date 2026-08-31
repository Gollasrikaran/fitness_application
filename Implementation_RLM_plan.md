# RLM Implementation Plan

Companion to [documentation_AGENT_RLM.md](documentation_AGENT_RLM.md) (the design) and
[RLM_Flowchart.md](RLM_Flowchart.md) (the diagrams). This plan is phased and cites real
files in the current tree so each phase is independently reviewable and testable.

---

## 0. What already exists vs. what this plan builds

Checked against the current codebase before writing this plan:

| Piece | Status | Where |
|---|---|---|
| `ActivityLog` (raw logging) | **Built** | [app/profile/models.py:98](app/profile/models.py#L98), write path in [app/profile/service.py](app/profile/service.py) `log_activity` |
| `UserProgram` (14.1 — program entries) | **Built** | [app/profile/models.py:147](app/profile/models.py#L147); create/read/update helpers already in `app/profile/service.py` (onboarding creation, active-entry queries, override handling) |
| `ActivityTaxonomy`, `SafetyGridCell`, `Condition` (13.3 grid, 4.0 taxonomy) | **Built** | [app/catalog/models.py](app/catalog/models.py) |
| Module 5 RAG rehab chat (`_retrieve_and_answer`, quota, memory, condition classification) | **Built** | [app/rag/service.py](app/rag/service.py) |
| **Module 15 — Progression Engine, data model** (`ProgressionHistory`) | **Built** | [app/progression/models.py](app/progression/models.py) |
| **Module 15 — Progression Engine, weekly job** (curve formula, guard chain) | **Built** | [app/progression/service.py](app/progression/service.py), scheduled via [scripts/run_weekly_progression.py](scripts/run_weekly_progression.py); tests in `tests/test_progression_curve.py`, `tests/test_progression_engine.py` — see §0a for gaps against the original design |
| **Module 16 — Program Agent** (proposal capability, recursive analysis) | **Not built** | — this plan, Phase 3–5 |
| Celery / scheduled-job infrastructure | **Not built** — referenced only in comments/docs (8.4); Phase 2's interim script-based approach was taken instead | — |

So this plan was not purely "bolt RLM onto existing Modules 15/16" — Phase 1–2 had to
build their baseline and the RLM curve extension together, since neither existed. That
part is now done. Phases 3–5 (the recursive analysis agent, its handoff into Module 5's
chat, and the 1.5× escalation guard) are still ahead and are what's specific to the
on-demand half of this feature.

### 0a. Gaps between this plan/the design doc and what got built

Recorded here and in [documentation_AGENT_RLM.md §11](documentation_AGENT_RLM.md) so
they're visible in both places, not just in a code comment. **Status re-confirmed
2026-08-21 against current code — no changes since first filed. 1 of 3 triaged gaps is
closed; 2 are genuinely deferred work, not resolved.**

| # | Gap | Status | Why |
|---|---|---|---|
| 1 | 15.3 discomfort-hold row | **OPEN — deferred** | Module 14.6 doesn't exist; no entry can have an open episode, so the row is vacuously safe but not implemented. Follow-up patch to `run_weekly_progression` needed once 14.6 ships. [service.py:14-16](app/progression/service.py#L14-L16) |
| 2 | 15.2 calibration-skip row | **OPEN — deferred** | Module 14.9 doesn't exist; no `calibrating` status on `UserProgram` to check. Same shape as #1 — harmless today, not done. [service.py:17-19](app/progression/service.py#L17-L19) |
| 3 | 14.5 "3× band ceiling" | **CLOSED — does not need revisiting** | Enforced as the reviewed per-activity `ActivityTaxonomy.max_amount × max_sets` instead of a fictitious 3× constant — a physiotherapist-set number, not a placeholder. More correct than the design doc's abstraction. [service.py:132](app/progression/service.py#L132) |

Two further concretizations, not yet run through this same triage — informational only:

- **The "<50% → reduce, same formula as 14.6d" row** has no real formula to reuse, since
  14.6d (soreness reduction) isn't built either. Implemented as an explicit flat
  `REDUCE_PCT = 0.10` default, documented as a stand-in, not the real 14.6d formula
  ([app/progression/service.py:54-58](app/progression/service.py#L54-L58)).
- **15.4's "absolute cap per adjustment"**, left abstract in the design doc, is
  concretely `MAX_ADJUSTMENT_PCT = 0.20`
  ([app/progression/service.py:43](app/progression/service.py#L43)).

**Bottom line:** #1 and #2 are safely deferred, not over — they need a small, explicit
follow-up once Module 14.6/14.9 are ever built, and Phase 3 (recursive analysis agent,
below) should not assume either exists.

---

## Phase 0 — Lock two config decisions

Blocking for Phase 1's schema. Defaults proposed in the design doc §9:

1. Growth metric = `ActivityLog.total_volume` (already logged) — confirm or change.
2. Condition-safety cache invalidated on profile edit (reuse 14.4's existing re-run
   trigger) vs. re-checked every chat turn — confirm or change.

If no objection, proceed with the defaults; both are single config values, cheap to
change later without a schema migration.

---

## Phase 1 — Data model ✅ built — see §0a for deviations

New package `app/progression/` (mirrors the existing `app/profile`, `app/rag` shape:
`models.py`, `service.py`, `routes.py`).

**`app/progression/models.py`:**

```python
class ProgressionHistory(Base):
    __tablename__ = "progression_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"))
    activity_type: Mapped[str] = mapped_column(String(64), ForeignKey("activity_taxonomy.activity_type"))
    old_target: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    new_target: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    adherence_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    curve_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)   # new vs. flat-rate baseline
    reason: Mapped[str] = mapped_column(String(32), nullable=False)           # "curve" | "hold" | "reduce" | "floor" | "escalation"
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_progression_history_user_activity", "user_id", "activity_type"),
    )
```

`curve_pct` is stored separately from the post-guard `adherence_pct`-driven change so
15.6's "why did my target change" can show the raw curve output alongside what actually
got applied after clamping — matches the design doc §8.

**Config table (or a static config module — either works for v1):** per-`activity_type`
or per-experience-band `k` constant for the curve formula (design doc §4.1). Given the
existing convention of small reviewed static tables (`program_templates`,
`activity_taxonomy`), add `k` as a column on `activity_taxonomy` rather than a new table
— one join, no new lookup path.

**Tests:** schema migration test, constraint tests (mirror the `CheckConstraint` pattern
already used on `UserProgram`).

---

## Phase 2 — Weekly diminishing-curve engine ✅ built — see §0a for deviations

**`app/progression/service.py`:**

```python
def compute_curve_increase(baseline_target: float, week: int, k: float) -> float: ...
def run_weekly_progression(session: Session, user_id: str) -> list[ProgressionHistory]: ...
```

- `compute_curve_increase` is the pure function from design doc §4.1 — unit-testable
  with no DB dependency. This is the highest-value test target: verify the shape (early
  weeks large, later weeks small, never negative) with property-based tests, not just
  example-based ones.
- `run_weekly_progression` implements 15.2's exclusions (suspended, calibrating,
  `user_override`, custom exercises — reuse the existing `UserProgram.status` /
  `source` columns, no new fields needed) then applies the guard chain from design doc §6
  (per-adjustment cap, 3× ceiling, 0.5× floor).
- Writes go through `session_scope()` ([app/platform/db.py](app/platform/db.py)) exactly
  like the existing activity-log write path — no new commit pattern to invent.

**Scheduling — pragmatic interim path:** no Celery worker exists in this codebase yet
despite being referenced in the architecture doc (8.4). Two options:

1. **Fast path:** a simple script (`scripts/run_weekly_progression.py`, matching the
   existing `scripts/` convention already used for `chunk_medquad.py` etc.) invoked by
   OS-level scheduling (cron / Windows Task Scheduler) — ships Module 15 without waiting
   on Celery infrastructure.
2. **Full path:** stand up the documented Celery low-priority queue and register this as
   a periodic task — matches 8.4/15.1 exactly, but is a larger prerequisite.

Recommend (1) now, with the job logic in `app/progression/service.py` kept decoupled
from *how* it's invoked, so migrating to (2) later is a scheduling change only, not a
rewrite.

**Tests:** unit tests for the curve function; integration test running the job against
a seeded set of `UserProgram`/`ActivityLog` rows covering each 15.3 adherence bucket
plus each 15.4/14.5 guard boundary (right at the floor, right at the ceiling).

---

## Phase 3 — Recursive analysis agent

**`app/progression/analysis.py`** (kept separate from the deterministic engine in
`service.py` — one file is pure arithmetic, the other calls an LLM):

```python
def analyze_performance(session: Session, user_id: str, activity_type: str, question: str) -> dict: ...
```

Implements design doc §5:
- Sub-check functions (`_check_adherence_trend`, `_check_plateau`, `_check_streak`,
  `_check_discomfort`, `_check_vs_curve`) — each a plain query against
  `activity_logs` / `progression_history`, **not** an LLM call. The LLM's only job here
  is deciding which sub-checks to run and whether a finding warrants recursion — the
  sub-checks themselves are deterministic, matching 15.5's reasoning against
  LLM-computed numbers.
- Recursion cap enforced in code (`max_depth=2`, `max_subchecks=6`), not left to the
  model's discretion — a runaway loop here is a cost/latency bug, not a feature.
- Returns the structured JSON from design doc §5.3. No free text — this function never
  produces the user-facing sentence.
- No caching/persistence of findings needed for v1 (Phase 0 decision) — recomputed per
  question. Revisit if latency/cost becomes an issue.

**Tests:** one test per sub-check with seeded data engineered to trigger it; a recursion-depth
test (plateau finding → deeper window, verify it stops at depth 2); a "no findings"
baseline test (verify it terminates fast with `summary_signal: on_track` and no
recursion).

---

## Phase 4 — Wire into Module 5's chat path

**`app/rag/service.py`** — in `_retrieve_and_answer` (currently at
[app/rag/service.py:462](app/rag/service.py#L462)):

- When the classified question relates to performance/progress (extend the existing
  `_classify_condition` / topic-routing logic already present, rather than adding a
  second parallel classifier), call `analyze_performance(...)` and inject its JSON into
  the prompt context alongside the retrieved medical chunks — same call, not a second
  LLM round-trip.
- The existing guardrail functions (`_enforce_no_medication_or_surgery`,
  `_approved_activities`) are unchanged and still run on the output — RLM's findings do
  not create a new path around them.
- Quota accounting (`_consume_quota` / `_refund_quota`) is unchanged — this is still one
  chat turn against the existing 5/day limit (5.4), not a separate budget.

**Tests:** extend existing `app/rag` test suite with a case where a performance question
produces an answer referencing both a retrieved medical fact and a findings value (e.g.
streak count) — verifies the handoff actually reaches the prompt, not just that the
function returns the right dict in isolation.

---

## Phase 5 — Escalation guard + proposal flow

- `analyze_performance`'s `escalation_proposal` (when `eligible: true`) is surfaced by
  the chat as a proposal, using the **same confirmation UI pattern already implied by
  16.5 / 5.6** ("Add this to your dashboard?") — no new UI pattern to design, reuse the
  existing add-exercise confirmation flow.
- On confirmation, the write goes through the **existing** `UserProgram` update path in
  `app/profile/service.py` (the same function Module 14's manual/agent/template writes
  already use) — confirms the 1.5× guard is enforced as one more clamp in that shared
  write path, not a new one specific to chat.
- **Test this phase adversarially**: write a test that tries to push a proposed increase
  above 1.5×, above the per-adjustment cap, and above the 3× ceiling independently, and
  confirm each guard fires regardless of what the other two would have allowed — guards
  should not silently rely on each other.

---

## Phase 6 — Dashboard graph

- Extend the existing dashboard summary endpoint (`GET /v1/dashboard/summary`, per
  REQUIREMENTS.md's API table, 4.3) to include the `curve_pct` series from
  `progression_history` per activity — additive field, not a new endpoint, so the
  existing frontend dashboard card in
  [app/devconsole/templates/app.html](app/devconsole/templates/app.html) only needs a
  new chart series, not new plumbing.
- Frontend: one more line/series on the existing growth chart component — percentage on
  the y-axis, week on the x-axis, matching the shape from the design doc's reference
  curve.

---

## Phase 7 — Rollout

- Feature-flag the weekly job and the chat analysis hookup independently — you can ship
  Phase 2 (silent backend curve) before Phase 3/4 (user-visible chat analysis) without
  waiting on the LLM-facing half.
- Log every escalation proposal and every guard clamp event (which guard fired, by how
  much it reduced the proposal) to existing observability (Module 10) — this is the data
  you'll want when tuning `k` per activity later.

---

## File/module map

| New file | Purpose |
|---|---|
| `app/progression/models.py` | `ProgressionHistory` table |
| `app/progression/service.py` | Curve formula, weekly job, guard chain |
| `app/progression/analysis.py` | Recursive sub-checks, findings schema |
| `app/progression/routes.py` | Any direct API needed (e.g. manual "run my analysis now" trigger for testing) |
| `scripts/run_weekly_progression.py` | Interim scheduler entry point (Phase 2, option 1) |
| `app/rag/service.py` (edit) | Hook `analyze_performance` into `_retrieve_and_answer` |
| `app/devconsole/templates/app.html` (edit) | New chart series on existing dashboard card |
