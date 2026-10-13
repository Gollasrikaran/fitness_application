# Per-Set Workout Tracking & Progression — Implementation Plan

Status: planning only, nothing built yet. This consolidates everything decided across
discussion into one concrete plan, ready to implement.

---

## 1. The problem this solves

Today, the app logs one uniform number per exercise ("2 sets × 5 reps"), assuming every set
is identical. In reality people do different numbers of reps per set (e.g. 10 / 8 / 6 as
fatigue sets in), and the weekly auto-progression system should both **capture that honestly**
and **progress each set on its own trajectory**, not blend them into one misleading average.

## 2. Data model — purely additive, not a rewrite

Add one new nullable column to `ActivityLog`: **`set_amounts`** — an array of numbers, one per
set (e.g. `[10, 8, 6]`). Only meaningful for `reps`/`hold` exercises — `distance`/`duration`
exercises (Walking, Running) are already locked to exactly 1 "set," so there's nothing to break
down for them.

When `set_amounts` is present:
- `sets_done` = length of the array
- `amount_per_set` = the **average** of the array (keeps the existing reps-ceiling trailing
  average working unchanged)
- `total_volume` = the **real sum** of the array × sides (strictly more accurate than today's
  "assume every set was identical" math — not a behavior change when sets happen to be equal,
  only more honest when they're not)

When `set_amounts` is absent (older client, or a quick manual log): everything works exactly as
it does today. Fully backward compatible — this is the property that keeps the change low-risk.

## 3. API change

`POST /v1/activities` gains one optional field per entry: `set_amounts`. Each value is validated
exactly like a single amount is today (finite, positive, within the existing caps) — once per
set instead of once per exercise.

## 4. The Workout Player interaction

Each set's value is tracked in the player's own local state as the user taps through them live
— no network call per set (this app already avoids per-set round trips on purpose; cross-region
request latency is a documented constraint elsewhere in this codebase). One real
`POST /v1/activities` call fires per *exercise*, carrying the full `set_amounts` array, when that
exercise's sets are done.

**Still open:** should each set's value be freely editable (type in what you actually did, like
the mockup), or a tap-to-complete checklist against the prescribed amount? Not yet confirmed —
flagging so it isn't silently decided either way.

## 5. Per-set independent progression (replaces one blended average)

Instead of averaging all sets into one number before progressing, **each set position gets its
own trailing average, computed independently**, and feeds the *same* existing curve-inversion
formula (`_reps_curve_step`) on its own.

- Averaged only over the days where that position was actually logged (handles a week where,
  say, Set 3 was only logged once because a set was added partway through the week).
- Sets are allowed to diverge and stay diverged — no forced reconciliation pulling them back
  together. Confirmed: this is intentional, reflecting real fatigue patterns rather than
  smoothing them away.

## 5a. Minimum-frequency gate — closes a real loophole in the existing formula

Found during this planning, not new to the per-set work, but fixed here since it directly
affects "when does growth happen at all": today, a single very strong day in a week is
mathematically enough to trigger growth, even with zero other activity that week — the existing
adherence check only averages logged days, never counts the days with no log as a zero. Example:
one day at 150% of target, nothing else logged all week → still averages to 150%, comfortably
over the grow threshold.

**Fix — gate the grow decision with a minimum real attendance count, without punishing good
performance:**
- Ratio below 50% → reduce (unchanged)
- Ratio 50-80% → hold (unchanged)
- Ratio 80%+ **and** logged on at least `MIN_LOGGED_DAYS_FOR_GROWTH` (3) different days this
  week → **grow**
- Ratio 80%+ **but** logged on fewer than 3 days → **hold, not reduce** — strong performance on
  the days they did show up is never penalized, they just haven't shown it often enough yet to
  earn an increase

Applies at the exercise-wide level (same level as the existing adherence check), before the
per-set independent growth in §5 runs.

## 6. New-set cascade — triggered only when a set hits its ceiling

**The exact trigger sequence (confirmed precisely, by set number — not a generalized rule):**

- **2 sets exist.** Set 1 hits its ceiling (Set 2 does not need to) → **this alone creates Set
  3.** Worked example (Set 1 = 30, just hit ceiling; Set 2 = 22, hasn't):
  1. Set 1 drops by its own drop percentage (see §7 — not a fixed number)
  2. Set 2 drops by its own drop percentage, independently
  3. New Set 3 = `NEW_SET_SHARE_FROM_LEADING` (30%) of Set 1's *original* value +
     `NEW_SET_SHARE_FROM_FOLLOWING` (40%) of Set 2's *original* value
  4. Cap: Set 3 must not exceed `NEW_SET_CAP_PCT_OF_FOLLOWING` (90%) of Set 2's *new* (post-drop)
     value — if it would, clamp it down to that 90%
  5. Result is always descending: Set 1 > Set 2 > Set 3
- **3 sets exist.** Set 2 hits its own ceiling → **this creates Set 4**, same cascade math
  (drop/redistribute/cap) applied across whichever sets exist at that point.
- **4 sets exist (`MAX_SETS_BEFORE_LEVEL_UP`) — the hard cap.** Set 3 hitting its ceiling here
  does **not** create a Set 5 — it only pushes Set 4's target higher, following this formula
  (confirmed, final):
  1. Start from Set 4's **normal weekly growth** this week — exactly what it would get anyway
     from the regular curve formula (§5), as if nothing special happened.
  2. Calculate an **extra boost %** = (Set 3's growth % *last week*) + (Set 4's growth % *last
     week*).
  3. Apply that extra boost on top of Set 4's normal result: `boosted = normal_growth × (1 +
     extra_boost_pct)`.
  4. **Hard cap at the ceiling (30)** — if the boosted result would exceed it, clamp down to
     exactly the ceiling instead.

  Worked example: last week Set 3 grew 26→28 (+7.7%), Set 4 grew 16→18 (+12.5%) → combined boost
  = 19.9% (≈20.2% before rounding). This week Set 4's normal growth would take it from 18→20 →
  boosted = 20 × 1.202 ≈ 24.04 → rounds to **24**. If the same math had instead produced 35, it
  would be clamped down to exactly **30**. There is never a 5th set, under any circumstance.
- **Only Set 4 itself hitting its own ceiling** triggers the next stage — §8 (Pro level), not
  another new set.

So, by set number: **Set 1 → creates Set 3. Set 2 → creates Set 4. Set 3 → boosts Set 4 only.
Set 4 → Pro level.** Each of the first three is a real, distinct rule — not one generic pattern
repeating — so any implementation needs to check for each one explicitly, by set position, not
infer it from a formula.

## 7. The drop percentage itself — a continuous formula, not fixed tiers

Confirmed: **no fixed bands** (e.g. "90%+ adherence → 15%, 70-90% → 25%, ..."), because a bucket
scheme creates an unfair cliff — two people at 89% and 91% adherence would get drastically
different outcomes for an almost-identical track record. Instead, a straight-line formula scales
smoothly across the whole adherence range:

```
drop_pct = MAX_DROP − (adherence − MIN_ADHERENCE) / (MAX_ADHERENCE − MIN_ADHERENCE) × (MAX_DROP − MIN_DROP)
```

With `MIN_DROP = 15%`, `MAX_DROP = 40%`, `MIN_ADHERENCE = 50%`, `MAX_ADHERENCE = 100%`:
- 100% adherence → 15% drop (gentlest landing)
- 75% adherence → 27.5% drop
- 50% adherence → 40% drop (most room given)
- 89% vs 91% adherence → ~18.8% vs ~18% (smooth, no cliff)

**Applied per set, using that set's own recent adherence** — not one blended number for the
whole exercise. This is a recommended default consistent with "each set has its own track
record" (§5), flagging it explicitly since it wasn't separately confirmed: Set 1 and Set 2 drop
by *different* amounts if their own recent adherence differs, not the same percentage for both.

This formula also uses existing data — adherence is already calculated every week for the
grow/hold/reduce decision (`_window_adherence`). No new signal needs to be collected.

## 8. "Pro level" — what happens after Set 4 also hits ceiling

No new input screen needed. Just:
1. Show a message: *"You've reached Pro level — this week is a test week. Do your workout like
   normal, and we'll set your new targets based on how you do."*
2. The user logs exactly like every other week — same screen, same flow, nothing new to build.
3. **The ceiling itself increases** (e.g. 30 → 50 reps) — a new, higher per-set ceiling for this
   exercise.
4. **The set count stays at exactly 4** — reaching Pro level never resets the set count back
   down, and never grows it past 4 either. It's the same 4 sets, now operating against a bigger
   range.
5. At the end of the test week, the **exact same weekly progression calculation and the same
   new-set cascade rules from §6-7** apply again — just re-anchored to the new ceiling. A small
   marker (e.g. a `ProgressionHistory` entry) records that this week is the fresh baseline point
   for the new ceiling.

## 9. Rounding — already built, zero new code

The existing `_round_reps()` function already does exactly the "half up" rule discussed
(`math.floor(amount + 0.5)` — 21.6 → 22, 21.3 → 21, never Python's default banker's rounding).
Every new number this plan produces for a reps-type exercise passes through this same existing
function before being shown to the user. Hold-type exercises (seconds) keep their own existing
step-snapping rule, unaffected — this rule is specifically for whole-number reps.

## 10. Constants — named in code, not `.env`

Every tunable number in this plan is a named Python constant, grouped with the existing ones
like `REPS_MAX_SETS` and `REPS_STANDARD_CEILING` — **not** an environment variable. These numbers
directly control how aggressively the app increases physical load for people with real medical
conditions; changing them should go through a real code change and review, not a casual
dashboard edit with no validation. (Already-existing `.env` settings like rate limits are a
different category — low-stakes operational knobs, not safety-adjacent math.)

```
SET_DROP_MIN_PCT            = 0.15
SET_DROP_MAX_PCT            = 0.40
SET_DROP_ADHERENCE_FLOOR    = 0.50   # adherence at/below this → max drop
SET_DROP_ADHERENCE_CEILING  = 1.00   # adherence at/above this → min drop
NEW_SET_SHARE_FROM_LEADING   = 0.30
NEW_SET_SHARE_FROM_FOLLOWING = 0.40
NEW_SET_CAP_PCT_OF_FOLLOWING = 0.90
MAX_SETS_BEFORE_LEVEL_UP     = 4
MIN_LOGGED_DAYS_FOR_GROWTH   = 3
```

## 11. Why not machine learning for any of this

Covered in discussion, summarized here for completeness: no deployed users yet means no training
data; per-user exercise history is too sparse for ML to learn from even once deployed; this is a
safety-critical calculation that needs to be explainable and auditable, which a trained model
isn't; and the formula above already achieves genuine per-user personalization (via each user's
own real adherence) without any of that risk or data requirement.

---

## Still open before implementation starts

Every formula in this plan is now confirmed with real numbers. Two small items remain:

1. Freely-editable per-set values vs. tap-to-complete checklist (§4).
2. Confirm §7's default: each set's drop uses *that set's own* adherence, not one shared number.

## Suggested build order

1. Schema + API (`set_amounts`, backward-compatible) — lowest risk, fully additive.
2. Minimum-frequency gate (§5a) — small, independent fix, no dependency on anything else here.
3. Per-set independent trailing averages replacing the single blended one (§5).
4. New-set cascade math + continuous drop formula (§6-7), including the Set-3-boosts-Set-4 case
   — these ship together, since the cascade depends on the drop formula to produce its numbers.
5. "Pro level" test-week flag + UI message (§8) — smallest piece, built last since it only
   triggers after the cascade above has run multiple times.
