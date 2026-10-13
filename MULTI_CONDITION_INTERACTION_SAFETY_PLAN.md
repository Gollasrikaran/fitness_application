# Multi-Condition Interaction Safety — Implementation Plan

**Status:** Mechanism fully built and tested (model, migration, loader,
service-layer integration, 14 passing tests, live-verified via 3 temp
accounts). **PENDING: doctor review.** Full 2,052-cell candidate matrix is
drafted at `data/condition_interactions_DRAFT_for_review.csv` (60 rows
flagged for real review, rest default to "no interaction found") — not
loaded into the app. Only 1 pair is actually live in production right now
(`arthritis_knee + obesity x running`, the original worked example). Next
step once the doctor reviews: copy approved rows into the real
`data/condition_interactions.csv` and re-run `python -m app.catalog.loader`.
No further code work needed on this feature until that review happens.

## 1. The gap (from APP_FEATURES_OVERVIEW.md)

> Handling the case where two conditions are individually fine with an exercise,
> but *together* make it risky — a combined-conditions safety check, designed
> conceptually but not yet built.

Today, `app/profile/service.py` computes safety per activity as the **worst
single-condition verdict** across all of a user's conditions (`_blocked_activities`,
`_modified_activities`, `_worst_verdict` — each does a UNION/MAX over
`SafetyGridCell` joined to `UserCondition`). There is no check for a condition
*pair* making an activity riskier than either condition alone would.

Real example already sitting in the data: `obesity` + `running` = `modify`.
`arthritis_knee` + `running` = `modify`. Individually both just say "favor
walking / reduce impact." **Together** — extra body weight multiplying the
repeated impact load on an already-damaged knee joint — that combination is a
real step up in risk, arguably `avoid` rather than two independent `modify`s.

## 2. Design principle (carried over from 13.3, not reinvented)

The existing safety grid's core rule: **static, reviewed, deterministic —
never LLM-generated, never inferred at runtime.** The interaction table follows
the same rule. The only difference is coverage:

- The single-condition grid requires **mandatory full coverage** (every
  condition × every activity reviewed, CI fails the build on a gap) because
  it's the *only* line of defense — missing coverage there must fail closed.
- The interaction table is **deliberately sparse**. It only ever *adds*
  restriction on top of the single-condition baseline that's already
  fail-closed. A pair with no row simply means "no additional risk is
  currently known for this combination" — it never means "assumed safe,"
  because each condition's own grid cell is still independently enforced.
  This is safe to leave sparse in a way the base grid never could be.

Escalation only ever goes one direction: `safe → modify → avoid`. An
interaction row can never loosen a verdict, so a `verdict=safe` row in the
interaction table would be meaningless — the loader rejects it outright.

## 3. Data layer

New file `data/condition_interactions.csv`:

```
condition_a,condition_b,activity_type,verdict,note,reviewer,reviewed_at,version
arthritis_knee,obesity,running,avoid,"Extra body weight multiplies the repeated impact load on an already-damaged knee joint — a materially higher risk than either condition alone. Prefer walking or low-impact cardio instead.",product-team (not clinically reviewed),2026-10-08,1
```

Seeded with this one real, defensible pair to start (both source cells are
already `modify` for `running` — see §1), enough to test end-to-end. More
pairs get added the same way the base grid grows: a reviewed CSV row, no code
change.

Loader rules (`app/catalog/loader.py`, new `load_condition_interactions`,
called from the same seed path as `load_safety_grid`):
- `condition_a != condition_b`.
- Both codes must exist and be in the **supported** bucket (a `refer`-bucket
  condition already blocks all content per 13.3b — interactions are
  meaningless there).
- `activity_type` must exist in the taxonomy.
- `verdict` must be `modify` or `avoid` — **never** `safe` (rejected as a
  loader error, not silently ignored, so a mistaken row gets caught at seed
  time, not discovered live).
- Canonicalize storage order: `condition_a < condition_b` lexically (loader
  swaps if the CSV author wrote them the other way) — so a lookup never has
  to check both orders, and a duplicate reverse-order row is a real DB
  constraint violation, not a silent duplicate.
- Reject duplicate `(pair, activity_type)` rows.

## 4. Model layer

`app/catalog/models.py` — new `ConditionInteractionCell`:
- PK: `(condition_a, condition_b, activity_type)`.
- `CheckConstraint("condition_a < condition_b")` — enforces canonical
  ordering at the DB level too, not just in the loader.
- `CheckConstraint("verdict IN ('modify','avoid')")`.
- Same provenance columns as `SafetyGridCell`: `note`, `reviewer`,
  `reviewed_at`, `version`.

New migration creates the `condition_interactions` table.

## 5. Service layer — extend the 3 existing choke points, don't duplicate

New helper in `app/profile/service.py`:

```python
def _interaction_verdicts(session, user_id) -> dict[str, dict]:
    """activity_type -> {"verdict", "note", "condition_a_code", "condition_a_name",
    "condition_b_code", "condition_b_name"} for every activity where some PAIR
    of the user's own conditions has a reviewed interaction row. Worst pair
    wins if more than one pair hits the same activity (same _VERDICT_RANK
    ordering _worst_verdict already uses)."""
```

Implementation: get the user's condition codes, `itertools.combinations(sorted(codes), 2)`,
query `ConditionInteractionCell` for rows matching any of those pairs, group by
activity_type taking the worst verdict.

Then, rather than three separate call sites re-deriving this, each existing
function folds it in:

- **`_blocked_activities`** — union with any activity where
  `_interaction_verdicts(...)[activity]["verdict"] == "avoid"`, even if no
  single condition alone says avoid.
- **`_modified_activities`** — same, for `"modify"`, skipping anything
  already in the blocked set (avoid still wins over modify, same precedence
  that already exists between these two).
- **`_worst_verdict(session, user_id, activity_type)`** — compares the
  existing single-condition worst against the interaction verdict for that
  one activity (if any) and returns whichever is more restrictive. Return
  shape grows a `kind` field: `"single"` (unchanged shape) or `"pair"` (carries
  both condition codes/names instead of one). Ties (both `avoid`) prefer the
  pair result, since it's the more specific, more informative reason to show
  the user.

Because `build_program`, `get_program`, and `add_program_entry` all already
call these three functions, **the dashboard, the daily suggestions, program
building, and the manual catalogue's override dialog all pick this up
automatically** — no separate wiring needed at any of those call sites. This
mirrors exactly how the single-condition grid already flows through the app
(13.7: "Module 13 becomes the daily view over" Module 14).

## 6. UX changes

`_override_warning` currently has one phrasing naming a single condition. Add
a second:

```python
def _override_warning_pair(condition_a_name, condition_b_name):
    return (f"You've told us you have both {condition_a_name} and {condition_b_name}. "
            "Together, this combination isn't recommended for this exercise, even though "
            "either one alone might be fine. Only continue if a doctor has examined you "
            "and specifically advised you to do it.")
```

`add_program_entry` picks whichever warning matches `worst["kind"]`.

`OverrideConsent` (app/profile/models.py) gets one new nullable column,
`condition_code_2` (FK to `conditions.condition_code`, NULL for an ordinary
single-condition override) — so a pair-triggered override is recorded
precisely: both conditions, not just one, the same "proof of what was shown"
guarantee the model's own docstring already promises for the single case.

## 7. Tests (backend, pytest)

New `tests/test_condition_interactions.py`:
- Loader rejects: `verdict=safe`, `condition_a==condition_b`, unknown
  condition code, a `refer`-bucket condition, unknown activity_type,
  duplicate pair+activity.
- Loader canonicalizes reversed-order CSV rows correctly.
- `_interaction_verdicts` returns nothing for a user with only one of a
  pair's two conditions, and returns the escalated verdict once they have
  both.
- `_blocked_activities`/`_modified_activities` reflect the escalation (e.g.
  `running` becomes blocked for a user with both `arthritis_knee` and
  `obesity`, even though each alone only modifies it).
- `add_program_entry` for `running` with both conditions returns
  `needs_confirmation` with the **pair** warning text and both condition
  names; confirming writes an `OverrideConsent` row with `condition_code_2`
  set.
- `build_program` auto-suspends an existing `running` entry when a second
  condition completing the pair is added (mirrors the existing single-condition
  suspend/resurrect logic already in `build_program`, same `condition_safety`
  suspension reason, same resurrection when the pair is broken again by
  removing one condition).

## 8. Manual frontend verification (temporary accounts, as requested)

Once the backend is implemented and migrated locally:
1. Sign up a **temp account A** through the real signup/onboarding flow,
   select only `arthritis_knee`.
2. Sign up a **temp account B**, select only `obesity`.
3. Sign up a **temp account C**, select **both** `arthritis_knee` and `obesity`.
4. For A and B individually: confirm `running` shows up normally in the
   program/Workout Player with its ordinary `modify` caution note (no
   escalation — proves single-condition behavior is unaffected).
5. For C: confirm `running` is now either suspended out of the program
   (if it pre-existed from template) or, when manually added via the
   catalogue's "+ Add exercise", triggers the confirmation dialog with the
   **pair-specific warning text** naming both conditions — proving the
   interaction layer actually fires end-to-end through the real UI, not just
   in isolated backend tests.
6. Delete/ignore the three temp accounts afterward (or leave them — your
   call; they're disposable test data, not real users).

---

Once this plan looks right, I'll implement in this order: migration + model →
loader + seed CSV → service-layer extension → OverrideConsent column → tests
→ manual verification per §8.
