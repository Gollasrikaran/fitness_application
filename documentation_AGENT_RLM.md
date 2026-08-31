# RLM — Recursive Performance Analysis Agent

**Status:** Design document. Extends Module 15 (Progression Engine) and Module 16
(Program Agent) from [REQUIREMENTS.md](REQUIREMENTS.md). Does not replace either.

---

## 1. Purpose

Today the app can log an activity (`ActivityLog`) and, per the existing spec, adjust a
user's program target weekly by a flat rule (Module 15.3: 5–10% if adherence ≥ 80%).
What's missing is:

1. A **progression curve** that starts aggressive and tapers — not a flat percentage —
   matching how real training adaptation works (fast novice gains, slower after).
2. A way for the **chatbot** to explain *why* a target changed, or analyze performance
   on request ("how am I doing", "can I do more this week"), grounded in the user's
   actual numbers rather than a generic reply.

"RLM" (Recursive Language Model, per the user's naming) is the mechanism for #2. It is
**not a new foundation model** — it is a bounded, recursive *decomposition agent* built
on the same LLM already used for Module 5/16, given a narrow tool: query the user's own
performance tables, break "how am I doing" into sub-questions, recurse only where a
sub-question flags something worth digging into, and return structured findings. Those
findings are hand-off input to the existing RAG-grounded chat (Module 5), which phrases
the final answer to the user.

---

## 2. Where this fits

| Existing module | Owns | RLM's relationship to it |
|---|---|---|
| **Module 14 — Training Program** | The program entry and its current target | RLM never writes here. Same boundary as 16.1. |
| **Module 15 — Progression Engine** | The weekly target-adjustment math | RLM **replaces the flat-rate formula in 15.3** with a diminishing curve (§5). The engine remains rule-based, no LLM, deterministic — 15.5's reasoning is unchanged and still applies. |
| **Module 16 — Program Agent** | Conversational proposals | RLM **is** the analysis capability bolted onto Module 16 — it gives the agent something grounded to say instead of generic chat. All of 16.1–16.6 (propose-only, retrieval-constrained, hard gate, confirmation required) apply unchanged. |
| **Module 5 — Rehab & Pain Guidance** | RAG-grounded synthesis, quota | RLM's structured output is additional context handed into the same `_retrieve_and_answer` prompt path — it does not bypass quota, guardrails, or the "model never prescribes" rule. |

> **Governing principle (unchanged from the existing spec, restated for this feature):**
> **Math decides the number. The LLM explains the number.** RLM never invents a target;
> it reads Module 15's numbers and the user's raw logs, and produces an explanation and
> (at most) a *proposal* to accelerate within guardrails Module 15 already enforces.

---

## 3. Two cadences

| | Weekly Diminishing-Curve Progression | On-Demand Recursive Analysis |
|---|---|---|
| Trigger | Scheduled batch job (extends 15.1) | User asks the chatbot about progress/suggestions |
| Engine | Pure arithmetic, no LLM | Bounded recursive decomposition using the LLM as a router, not a calculator |
| Output | New target + `progression_history` row (unchanged shape, 15.6) | Structured findings JSON → phrased by Module 5's answer LLM |
| Can it write? | Yes — this is Module 15's existing authority | **No.** Proposes only, per 16.1 |

---

## 4. Weekly Diminishing-Curve Progression (extends 15.3)

### 4.1 Formula

Replaces the flat "5–10% if adherence ≥ 80%" step with a log-shaped curve so the
increase is largest early and tapers, without ever going negative or unbounded:

```
capacity(week)      = baseline_target * (1 + k * ln(1 + week))
weekly_increase_pct = capacity(week) / capacity(week - 1) - 1
```

- `week` counts from the program entry's start (0-indexed), so `ln(1 + week)` is always
  defined and non-negative — the domain problem with raw `ln(x)` at `week = 0` doesn't
  occur.
- `k` is a per-activity or per-experience-band tuning constant (config, not hardcoded) —
  this is what lets 14.5's experience-band ceilings and 15.4's absolute-cap guard stay
  meaningful across activities with different natural progression rates.
- As `week → ∞`, `weekly_increase_pct → 0` but never reaches it — matches the "high at
  first, reduced later, never fully flat" shape from the reference curve.

### 4.2 Guard reconciliation — nothing new is exempt

Every existing guard in 15.2/15.4 still applies to the *output* of this formula, unchanged:

- Adherence still gates whether an increase happens at all (15.3's ≥80% / 50–79% /
  <50% / open-discomfort table is unchanged — only the ≥80% branch's *magnitude* comes
  from the curve instead of a flat 5–10%).
- **Absolute cap per adjustment (15.4)** still clamps the curve's output — if `k` is
  misconfigured and the curve suggests a large jump, the existing per-adjustment ceiling
  still wins.
- **Floor at 0.5× baseline (15.4)** and **ceiling at 3× baseline (14.5)** are unchanged.
- Suspended, `user_override`, and custom-exercise entries are still excluded exactly as
  15.2 already specifies.

This means the curve is a **replacement for one number inside 15.3**, not a new system
with its own guard set. **See §11 for which of these guards are actually wired in the
current codebase** — two of them (calibration-skip, discomfort-hold) are not reachable
yet because the modules they depend on aren't built.

---

## 5. On-Demand Recursive Analysis (extends Module 16)

### 5.1 What "recursive" means here

Not a special model architecture — a bounded agent loop:

1. The user's question is decomposed into candidate sub-checks (not all run every time):
   - Adherence trend (last 4 vs. previous 4 weeks)
   - Plateau detection (adjustment magnitude flattening in `progression_history`)
   - Consistency / streak (existing 4.2 streak data)
   - Discomfort history on the entry in question (14.6) — **currently a no-op, see §11:
     Module 14.6 doesn't exist yet, so there is no discomfort data to check**
   - Comparison against the weekly-batch curve's own prediction for this week
2. Each sub-check either returns "nothing notable" or a finding. **Only findings
   trigger recursion** — e.g., a plateau finding triggers a deeper look at the last 8
   weeks instead of 4; a discomfort finding triggers a check of whether the entry is
   currently suspended.
3. Recursion is bounded: **max depth 2, max sub-checks 6 per user question** (config).
   This is a cost and latency control, not a tuning knob for "more thorough analysis" —
   see 15.5's reasoning: unbounded LLM-driven analysis is exactly what that section
   argues against for anything touching a number that reaches the user.
4. Terminates with a **structured findings object** (§5.3) — never free text at this
   stage. Free text is Module 5's job, not this agent's.

### 5.2 What the recursive agent is explicitly not allowed to do

Same boundary as 16.1, restated for this capability specifically:

- It cannot write to `user_program` or `progression_history` — only Module 15's batch
  job writes progression state.
- It cannot invent a number outside what §6 (the escalation guard) allows.
- It cannot select or name an exercise not already in the user's program or the
  safety-grid-filtered candidate set (16.2) — an analysis question is not a backdoor
  around the retrieval-constrained selection rule.
- It cannot skip the hard gate (16.3) or confirmation requirement (16.5) if its output
  leads to any proposed change.

### 5.3 Structured output schema (handoff contract to Module 5)

```json
{
  "summary_signal": "on_track | ahead_of_plan | plateaued | behind | discomfort_flagged",
  "findings": [
    {"check": "adherence_trend", "value": 112, "window_weeks": 4, "trend": "improving"},
    {"check": "plateau", "detected": false},
    {"check": "streak", "current": 18, "longest": 21}
  ],
  "escalation_proposal": {
    "eligible": true,
    "proposed_pct_increase": 0.10,
    "capped_at": 0.5,
    "reason": "adherence 112% over 4 weeks, no plateau detected. Discomfort is not yet tracked by this app, so this is not a discomfort-cleared recommendation."
  },
  "condition_gate": {"checked": true, "cached": true, "safe": true}
}
```

(`proposed_pct_increase` is now one of exactly 0.05/0.10/0.15 — see the revised §6 below —
not an arbitrary value between 0 and the 0.5 cap. `condition_gate.cached` is `false` in
the actual implementation, since no caching layer exists yet — see §11 gap-adjacent note.)

This is what gets injected into Module 5's `_retrieve_and_answer` prompt context
alongside the retrieved medical chunks — the answer LLM sees both "what's medically true
for this condition" and "what's true about this user's numbers" in the same call, and
phrases one coherent, encouraging answer. **The answer LLM still never invents a target
or names an unapproved exercise** — those rules (5.3) are unchanged.

---

## 6. The 1.5× Escalation Guard

**Revised 2026-08-21** (implemented in `app/progression/analysis.py`): the 1.5× figure
below is the absolute worst-case backstop, not the target size of a real proposal — a
real proposal should almost never get near it. What actually gets proposed is a small,
discrete step, sized to how far above 100% the user's adherence has been:

> **A real proposal is one of exactly three fixed sizes — +5%, +10%, or +15% — chosen by
> the agent based on how consistently the user has cleared 100% adherence (up to the
> 150% adherence cap from 15.2).** Eligibility itself requires adherence ≥ 100% (not the
> ≥ 90% originally sketched here), no plateau, a non-declining trend, and a safe
> condition-gate check. The **1.5× ceiling remains as an independent, always-applied
> backstop** below — every one of the three step sizes is already far under it, so in
> normal operation the ceiling should never be the thing doing the clamping.

Which of the three step sizes to propose is deliberately the *one* number in this whole
feature actually left to the LLM's judgment (`_pick_escalation_step`) — but only a choice
among three fixed, code-defined values, snapped to the nearest one no matter what text
comes back (`_snap_to_step_choice`), and failing closed to the smallest step (+5%) on any
LLM error. This does not weaken "math decides the number, the LLM explains the number"
(§5's governing principle) — the LLM picks *which* of three pre-decided numbers, not an
arbitrary one, the same way the recursion router (§5.1) picks *whether* to recurse
without ever inventing depth or breadth beyond what's coded.

Ordering of guards, tightest-relevant-one-wins:

```
final_proposed_increase = min(
    step_choice,                  # +5% / +10% / +15%, picked by _pick_escalation_step
    1.5x_escalation_guard,        # this document, on-demand path only — worst case, not the target
    per_adjustment_cap (15.4),    # existing — always applies
    taxonomy_ceiling (14.5)       # existing — see §11 gap #3: the real per-activity ceiling
)
```

The escalation proposal is **always a proposal**, never a write — it still needs
explicit user confirmation (16.5) and still passes the write-time hard gate (14.3/16.3)
before Module 15's tables change.

---

## 7. Percentage graph (dashboard)

The weekly curve (§4.1) naturally produces a "big jump early, smaller jump later" series
per activity. This is exactly the graph shape the user referenced. It's computed once
per batch run (§4) and stored, not recomputed per page view:

- Backend: expose `weekly_increase_pct` history per program entry (already implied by
  `progression_history.adherence_pct` sibling columns — add `curve_pct` alongside it,
  see Implementation plan §1).
- Frontend: the existing dashboard growth-chart surface (4.3 / 11.3) gets one more
  series — no new UI surface needs inventing.

---

## 8. Data model additions (see Implementation_RLM_plan.md for full detail)

- `progression_history` gains a `curve_pct` column (the diminishing-curve output before
  guard clamping) alongside its existing `adherence_pct`, so "why did my target change"
  (15.6) can show both the trend-based number and what was actually applied.
- No new table is required for the recursive agent's findings — they are computed
  on-demand and not persisted (see Implementation_RLM_plan.md, Phase 3, for the
  caching decision this implies).

---

## 9. Open configuration decisions

These are documented as **assumed defaults**, not silent choices — flag if they should
change before implementation locks them in:

1. **Growth metric = total volume** (`sets × amount`, i.e. `ActivityLog.total_volume`,
   already logged today). Per-exercise weight progression and session-count metrics are
   not modeled in v1.
2. **Condition-safety check is cached from the user's profile** and only re-run when the
   profile changes (14.4's existing re-run-the-grid trigger already covers this) — the
   recursive agent's `condition_gate.cached: true` reads that cache rather than
   re-querying the safety grid on every chat message.

---

## 11. Known implementation gaps (filed against the actual build)

The weekly engine (§4) is built — [app/progression/service.py](app/progression/service.py)
— and its docstring documents the same gaps recorded here. This section exists so the
gaps are visible from the design doc too, not only from a code comment.

**Status re-confirmed 2026-08-21, re-checked against current code, no changes since
first filed: 1 of the items below is closed. The other two are genuinely deferred work,
not resolved — they are currently harmless, not currently done.**

**Two 15.2/15.3 rows are structurally unreachable right now — OPEN, deferred:**

1. **"Open discomfort episode → hold" (15.3) — OPEN.** Module 14.6 (per-exercise
   discomfort reporting) genuinely doesn't exist in the codebase. The weekly job can't
   skip something that can never be true, so this guard is currently **vacuously
   safe** — no entry can ever have an open discomfort episode, so nothing wrongly gets
   increased — but it is not actually implemented. **Follow-up trigger:** when 14.6 is
   built, `run_weekly_progression` needs a follow-up patch to check it
   (`app/progression/service.py:14-16`). Pending, not done.
2. **"Entries in calibration are skipped" (15.2) — OPEN.** Module 14.9 (calibration)
   doesn't exist either — no `calibrating` state exists on `UserProgram.status`. Same
   situation: currently harmless because nothing can be "in calibration," but the
   exclusion itself isn't implemented, just unreachable. **Follow-up trigger:** patch
   once 14.9 exists (`app/progression/service.py:17-19`). Pending, not done.

**One guard was made concrete against real code and is genuinely resolved — CLOSED:**

3. **The "3× band ceiling (14.5)" — CLOSED, does not need revisiting.** `run_weekly_progression`
   uses `ActivityTaxonomy.max_amount × max_sets` as the real ceiling instead of a
   fictitious 3× constant (`app/progression/service.py:132`). That taxonomy ceiling is
   already the reviewed, physiotherapist-set maximum per activity — it is not a
   placeholder standing in for something better; it is the more correct and
   safety-grounded choice against an arbitrary 3× multiplier. "3× baseline" in §4.2/§6
   should be read as "the reviewed taxonomy ceiling."

**Two more concretizations, not yet re-confirmed in the same triage pass — still
recorded as open/informational until reviewed the same way as 1–3 above:**
4. **The "<50% → reduce, same formula and floor as 14.6d" row (15.3)** — 14.6d (soreness
   reduction) is also not built, so there is no real formula to reuse. The current
   implementation uses an explicit, documented flat default,
   `REDUCE_PCT = 0.10` (`app/progression/service.py:54-58`), standing in for it. This is
   called out in code as a stand-in, not presented as the real 14.6d formula.
5. **15.4's "absolute cap per adjustment"** — left abstract in this design doc as "the
   configured percentage" — is concretely `MAX_ADJUSTMENT_PCT = 0.20`
   (`app/progression/service.py:43`), chosen to sit above the old flat-rate's 5–10% since
   the curve is meant to start more aggressive than that, while still bounding a
   misconfigured `k`.

**Why this section exists rather than quietly matching the doc to the code:** inventing
a fake `calibrating` column or a fake 14.6d formula to make §4.2's guard list technically
true would hide that Modules 14.6/14.9 still need building. Recording the gap here (and
in the implementation plan, §0) keeps that visible instead of buried in a diff.

---

## 12. Explicit non-goals

- This is not a new model to train or fine-tune. "Recursive" describes the *agent's
  control flow*, not a model architecture change.
- This does not change who is allowed to select exercises (16.2 unchanged) or bypass any
  existing safety gate.
- This does not remove the 0–6 month experience-band scope limit (14.5) — the curve and
  the escalation guard operate inside that same population.
