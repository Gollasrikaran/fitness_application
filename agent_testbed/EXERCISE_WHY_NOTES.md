      # The "why" under each exercise: status and next steps

Written 17 November 2026, to continue on 18 November. Context for whoever
picks this up (including the AI assistant).

## What we wanted

In the doctor's review card, each exercise should say **why it was chosen
for this patient**, in a way a doctor finds useful, and without the AI
making up medical facts. Before today, these reasons were one block of lines
inside "Why this draft", and they were generic ("strengthens the legs").

## What we built today (in order)

| Step | What | Why |
|---|---|---|
| 1 | Moved each exercise's reason from "Why this draft" to **under the exercise** (after the sets and dose, before the note for the patient). "Why this draft" keeps only the AI's short summary and the rule lines | The user's request |
| 2 | **Research lines**: new file `backend/data/exercise_benefits.csv`, 60 lines (condition × exercise, with source): BP, diabetes, prediabetes, knee, hip, back, hand, asthma, skin | The reasons were generic because the AI may not make medical claims |
| 3 | First version showed **our research line only** | Accurate, but repetitive, and a lot of manual work to cover every condition |
| 4 | **Plan C (current):** the AI writes every reason in its own words; our research lines are its only source of health facts; a **code check** drops an AI reason containing a number that isn't in the evidence (or the patient's own age / BMI) and shows our research line instead | Natural, specific wording without invented facts |
| 5 | The AI now gets each condition's **notes** (advice), so the patient's instructions include it | The skin advice was missing from the instructions |
| 6 | **Skin advice split**: everyone dries well and changes into dry clothes; eczema: moisturiser after drying; fungal infection: keep dry, no cream unless prescribed | A first test told a tinea patient to moisturise |
| 7 | **Short condition names** in the research lines ("Skin problem:" not "Skin problem (eczema, fungal infection):") | Readability |
| 8 | A retest failed: the AI answered with the plan parts' names ("leg strength") instead of exercises, so the rules drafted the plan with **no reasons**. Fixed: a part's name means that part's best fit; the prompt says "return one activity_type, not the part's name"; the walking line no longer says "don't return it" (it contradicted "write a why for walking"); **rules drafts also get a reason** under each exercise | Bug found while testing |

## How it works now

For each exercise in a draft, `agent/draft.py` → `_why()`:

1. **The AI's reason**, if it gave one **and** every number in it appears in
   that exercise's research lines or in the patient's age / BMI.
2. Otherwise **our research line(s)** for the patient's conditions, e.g.
   "BP under control: walking-type exercise lowers resting BP by about 4-7
   mmHg, and one session keeps it lower for up to a day."
3. Otherwise a **standard line**: "Main exercise of the plan, always first
   (set by the safety rules)." or "Leg strength: the best-ranked option for
   this part of the plan (chosen by the safety rules)."

Rules drafts (when the AI fails) use steps 2–3 only.

The reason is stored on each draft exercise (field `why`). It is **never
shown to the patient** and is not kept in the approved plan.

**Files:** `backend/agent/draft.py` (`_why`, `_numbers`, `_rules_whys`,
`_from_ai`, `_ask_ai`), `backend/agent/prompts.py` (`DRAFT`),
`backend/store/plans.py` (`approved_exercises`, `candidates`: the `benefits`
per exercise), `backend/store/seed.py` + `store/models.py`
(`SafetyRule.benefit`), `backend/data/exercise_benefits.csv`,
`backend/data/conditions.csv` (skin notes),
`frontend/src/AgentPanel.jsx` (shows "Why: …").

**Tests:** `backend/tests/test_draft.py` (the "why" tests at the end); all
**368** backend tests pass.

## Outputs seen (patient 6959e408: BP, BMI 31.2, tinea)

Three drafts were generated on the screen today:

| Run | Result | What we learnt |
|---|---|---|
| Before plan C (research lines only) | AI draft; every reason was our research line | Accurate, but Sit to Stand and Wall Push-up had the identical BP line; the AI's instructions told him to **moisturise** (wrong for tinea) |
| Plan C, first try | **Rules draft**, no reasons | The AI returned part names ("leg strength"); fixed (step 8) |
| Plan C, after the fix | **AI draft**, reasons below | Works; details to improve (next section) |

The last run's reasons:

| Exercise | Reason shown | Verdict |
|---|---|---|
| Walking | Walking lowers resting BP by about 4-7 mmHg and is suitable for skin problems. | BP part good (from our evidence); "suitable for skin problems" vague |
| Sit to Stand | Strengthens the thighs, which supports mobility and helps manage weight. | "Helps manage weight" is a claim **without evidence**; the BP evidence (4–5 mmHg) wasn't used |
| Wall Push-up | Works the upper body muscles, which aids in overall strength and fitness. | Generic; BP evidence not used |
| Standing on One Leg | Balance: the best-ranked option for this part of the plan (chosen by the safety rules). | The AI gave no reason; standard line shown |
| Slow Breathing | Promotes relaxation and can help lower BP by about 5 mmHg. | Good (from our evidence) |

Patient instructions (good): cool time of day, go slowly, the stop signs,
wash with lukewarm water, dry well, change into dry clothes, broken or
oozing skin → tell the doctor; no moisturiser. Missing: loose cotton
clothes, don't share towels.

The number check worked: both numbers the AI wrote came from our evidence.

## What still needs correcting (proposed, not built)

1. **Show our evidence under the AI's reason when the AI didn't use it**
   (Sit to Stand, Wall Push-up above), so the doctor always sees the
   research. E.g. "Why: Strengthens the thighs… · Evidence (BP): strength
   exercise with movement lowers resting BP by about 4–5 mmHg".
2. **Claims in words aren't checked**, only numbers ("helps manage weight").
   Options: (a) tell the AI more firmly to name a condition only when the
   option has EVIDENCE for it; (b) a code check for health words ("weight",
   "sugar", "BP", "pain"…) when that condition has no evidence line for the
   exercise; (c) accept, since the doctor reviews every plan. Recommended:
   (a) + item 3, then see.
3. **Overweight evidence lines** in `exercise_benefits.csv` (research we
   have: ACSM 2022 in `research/DIABETES.md`, about 500 kcal on 4–5 days a
   week for weight loss; chair-based strength avoids the floor), so weight
   claims have a real source.
4. **Better standard line for balance** (and the other parts) when the AI
   gives nothing, e.g. "Balance: trains steadiness on the feet (general; no
   condition-specific evidence)". The AI skipped balance's reason despite the
   prompt (gpt-4o-mini doesn't always follow it).
5. **Patient instructions: two skin steps missing** (loose cotton clothes,
   don't share towels). Tell the AI to keep every step of the condition's
   advice, or add the advice in code after the AI's sentences.
6. **Rules drafts' patient instructions** say "Starter plan built from the
   safety rules for: …", which is text for the doctor, not the patient.
   Proposed: simple patient instructions plus the conditions' advice.
7. **The AI's assessment summary** sometimes leaves out a condition
   ("hypertension and tinea", no obesity). Minor; the conditions list is
   right.

## To do tomorrow

1. Decide items 1–7 above; build the agreed ones.
2. Restart the backend (or push so Render restarts), then "Generate again"
   on 6959e408 and check the reasons and instructions.
3. Also test the other dashboard patients (`TESTING_CHECKLIST.md`, Round 2):
   #32 bdbdc1f3 (not tested yet), retest #30, #31, #33.
4. Commit today's work (nothing is committed yet; the live site doesn't have
   it).

Related: `WORK_SUMMARY_2026-11-17.md` (the whole day), `PROPOSED_CHANGES_2026-11-17.md`
(joint, hand and skin changes), `KNOWN_ISSUES.md` #14 (scanned documents).
