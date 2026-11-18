# Next phase: the right exercises for each patient

Agreed in the meeting (2026-10-28). Context for the work after the current task.

## Who owns what

| A colleague: who may exercise | Us: what they should do, and how much |
|---|---|
| Severity, refer conditions, warning complaints, "doctor must write" | The exercise library: which exercises exist, how each is done, safe doses |
| `agent/assess.py`, `agent/routing.py`, `data/warning_complaints.csv` | `exercises`, `safety_rules`, `store/plans.py` → `candidates()`, `agent/draft.py`, doses |
| KNOWN_ISSUES.md #1, #5, #6, #7, #9 | KNOWN_ISSUES.md #10, and the work below |

**To agree with the colleague:** what they hand us. Expected: "this patient is
eligible", their conditions, and their latest readings (BP, sugar, BMI, age,
Hb, pulse, SpO2, medicines). Our work starts where their output ends.

## What we build

1. **A richer exercise library.** Today: 12 exercises with name, sets and
   amount only. For each exercise add:
   - type: aerobic, strength, isometric, stretching, balance, breathing
   - intensity: light, moderate, vigorous
   - position: standing, chair, floor (getting down to the floor matters for
     older, overweight and knee patients)
   - impact, and whether it involves straining or holding the breath (the main
     BP risk)
   - instructions (Hindi later)

   And add exercises: chair-based, balance, breathing, gentle isometric (for
   example a wall sit).

2. **Rules by reading, not just by condition.** Today the grid says "safe for
   BP under control" whatever the reading. Add rules by band:
   - **BP:** limits by the latest systolic/diastolic band (for example no
     breath-holding above a level, or walking only)
   - **Sugar:** fasting and random levels; low-sugar risk for patients on
     certain diabetes medicines (we have medicine names); foot care
   - **BMI:** low impact; no floor exercises above a level
   - **Age:** balance and chair options for older patients
   - **Haemoglobin (anaemia), pulse, SpO2:** lower intensity

3. **A balanced plan, not just a list.** Mix walking-type activity, strength,
   stretching and breathing, and add how often and how long: days per week,
   minutes per session, and how hard it should feel. Plans have none of this
   yet.

4. **Research to fill in 1–3**, one condition at a time, starting with
   hypertension. Sources: guidelines (WHO, Indian hypertension and ICMR
   guidelines, ACSM), studies, and the Kaggle datasets (via Claude on the web,
   with `RESEARCH_CONTEXT.md` as its brief). For each recommendation: the
   exercise, the dose, the readings it suits, what to avoid, the evidence.

5. **Matching.** Code that takes a patient's conditions and readings and picks
   the best-fit balanced plan under the new rules. The AI can still order and
   explain; the rules decide what is allowed and the doses.

6. **Checking.** A dry run on eligible patients (plans should vary sensibly
   with the readings), doctor reviews recorded via `GET /review-summary`, and
   a clinician's sign-off of the new library and rules.

## Order

1. Agree the hand-over with the colleague.
2. Hypertension research → BP bands, exercise types, doses, what to avoid.
3. Extend the exercise library's fields; add the exercises the research supports.
4. Matching for hypertension end to end, then diabetes, knee and back, overweight.

## What we already know about hypertension (2026-10-27)

- 6,529 of 41,045 adult clinic patients (16%) have hypertension recorded; for
  3,126 of the 6,419 with a reading (49%), the latest BP is flagged HIGH or
  CRITICAL.
- Our grid for "BP under control": all 11 gentle exercises safe with the same
  generic note; running "modify". Nothing about breath-holding or straining.
- The reference DB's medical text has nothing on hypertension itself.
- Candidates to research: walking-type activity, isometric exercise (wall
  sit), slow breathing; a "no exercise today" BP level; breath-holding.

Research done 2026-10-28: `research/HYPERTENSION.md` (evidence, guidelines,
safety, and proposed bands, plan shape and new exercises, to decide).

## Progress

- **2026-10-28, steps 1–3 done:** 5 exercises added to `data/activity_taxonomy.csv`
  from the hypertension research: Wall Sit (hold), Sit to Stand and Wall Push-up
  (repetitions), Marching on the Spot and Slow Breathing (new type `time`, in
  minutes). Their steps are in the CSV's new `instructions` column, used when
  the reference DB has none. They have safety-grid rows like the original 12 (product team, not clinically
  reviewed; the whole grid goes to a clinician together): 100 rows, 78 safe and
  22 modify (e.g. wall sit "modify" for BP, knee, hip, disc, overweight; Marching
  copies Walking's verdicts). Ranked 13–17, after the original 12, so drafts for
  other conditions don't change. Doses are cautious placeholders (e.g. wall sit
  2 × 20 s, max 4 × 60 s). Tests: `backend/tests/test_new_exercises.py`.
- **2026-10-28, BP only (`bp_controlled`):** re-ranked so the research-backed
  exercises come first (Walking, Marching, Sit to Stand, Slow Breathing, Wall
  Push-up, then the rest), and Neck Hold, Glute Bridge and Dead Bug changed from
  "safe" to "modify" with "breathe normally; don't hold your breath" (a note on a
  "safe" row never reaches the doctor or the AI). Other conditions unchanged.
- **Next:** exercise properties and the BP bands (step 4).

## Open question

Does "etc." in the scope include diet and lifestyle advice, or only exercise?
