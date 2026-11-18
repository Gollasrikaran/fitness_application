# Exercise fit: tracker

Tick items as they land (`[x]`), with the date. The why and the background are
in `EXERCISE_FIT_PLAN.md`; the research per condition is in `research/`.

## How a plan is chosen (target flow)

```
Colleague's eligibility  ─→  eligible patient + conditions + latest readings
                                        │
Exercise library (25)    ─→  every exercise, with doses, steps and properties
  data/activity_taxonomy.csv              (type, intensity, breath-holding, position, impact)
                                        │
Safety grid by condition ─→  drop "avoid"; keep "modify" with its note
  data/safety_grid.csv                    (one verdict per condition × exercise)
                                        │
Rules by reading         ─→  drop what the patient's BP, sugar, Hb, SpO2, resting pulse rule out
  data/reading_rules.csv                  (e.g. BP 150/95: no holds, no vigorous; Hb 7: no plan)
                                        │
Age / BMI rules          ─→  at 60+ or BMI 30+: nothing high impact or on the floor;
                              doses one step lower at 60+
                                        │
AI orders and explains   ─→  picks 3–5 from what's left; never sets doses
                                        │
Rule check               ─→  any break → rules-only draft instead
                                        │
Weekly plan (step 5)     ─→  NOT BUILT YET: days a week, minutes, how hard (talk test);
                              a mix of walking-type, strength, breathing, stretching
                                        │
Doctor edits, approves   ─→  nothing blocked; small warnings
                                        │
Patient plan page        ─→  approved plan only
```

Everything is read from the temp DB at runtime; the CSVs are loaded into it at
every backend start.

## Steps

### Step 0: Ownership and inputs
- [x] Scope agreed: a colleague decides who may exercise; we decide what and how much (2026-10-28)
- [ ] Hand-over agreed with the colleague: what she gives us (eligibility, conditions, readings) and from where (her API)
- [ ] Switch `app/clinic.py` to her API once the URL is ready (`CLINIC_DATA_WE_USE.md`)

### Step 1–3: More exercises (hypertension)
- [x] Hypertension research: `research/HYPERTENSION.md` (2026-10-28)
- [x] 5 exercises added: Wall Sit, Sit to Stand, Wall Push-up, Marching on the Spot, Slow Breathing (2026-10-28)
- [x] New exercise type `time` (minutes); patient page says "5 minutes" (2026-10-28)
- [x] Steps for exercises the reference DB has none for: `instructions` column in our CSV (2026-10-28)
- [x] Safety-grid rows for the 5 × 20 supported conditions (100 rows, product team) (2026-10-28)
- [x] BP only: research-backed exercises ranked first; "don't hold your breath" on Neck Hold, Glute Bridge, Dead Bug (2026-10-28)

### Step 4: Rules by reading (BP first)
- [x] Exercise properties on all 17: type, intensity, breath-holding, position, impact (2026-10-28)
- [x] `data/reading_rules.csv`: BP bands (2026-10-28)
  - below 140/90: nothing extra
  - 140–159 / 90–99: no isometric holds, no vigorous
  - 160–179 / 100–109: only walking-type (not vigorous), breathing and mobility
  - 180/110 or above: no exercise plan (eligibility; doctor decides)
- [x] Which reading: the latest in the last 90 days; the stricter of systolic and diastolic (2026-10-28)
- [x] No reading in 90 days and the patient has BP: treated as 140–159 / 90–99 (cautious default) (2026-10-28)
- [x] AI drafts: ruled-out exercises removed before the AI chooses; the draft says why (2026-10-28)
- [x] Doctor: a small warning ("not advised at BP 150/95"), never blocked; picker shows "(not advised)"; the assessment box shows the BP used (2026-10-28)
- [x] Tests: `backend/tests/test_reading_rules.py` (20) (2026-10-28)
- [x] More readings in the same file: sugar, Hb, SpO2, resting pulse (product team, provisional; 2026-10-28)
  - sugar 250–299 mg/dL: no vigorous; 300 or above, or below 70: no plan, a doctor decides
  - Hb below 10 g/dL: no vigorous; below 8: no plan
  - SpO2 below 94%: no vigorous; below 92: no plan
  - resting pulse 100–119 or below 50: no vigorous; 120 or above, or below 40: no plan
  - no reading in 90 days: no rule (only BP has a default); typing errors (e.g. SpO2 970) skipped
  - the doctor's assessment box lists every reading used
  - lab results from uploaded reports count for 6 months (2026-11-04)
  - the doctor can include older readings (6 months or a year) at Generate plan; they can only make
    the plan stricter, and an old BP counts only if 140/90 or above (2026-11-04)
- [x] Tests for them: 29 more in `test_reading_rules.py` (2026-10-28)
- [ ] Clinician reviews all reading bands (with the grid, step 7)
- [ ] Medicine rules: insulin / sugar tablets (low-sugar warning), beta-blockers (talk test)
- [ ] Try on real patients (needs the clinic DB or the colleague's API)

### Step 5: A weekly plan, not just a list
- [ ] Plan format: how often (days a week), how long (minutes), how hard (talk test)
- [x] A balanced mix (2026-11-16): walking-type first, then leg strength, upper-body strength, balance, and breathing last as the cool-down; each the best-ranked allowed exercise of its type (`store/plans.py` → `plan_slots()`). The AI picks one of each slot's best 3. New `body_part` column (upper / lower / core) on the strength exercises. Holding exercises are never a slot. Example 6959e408: Walking, Sit to Stand, Wall Push-up, Standing on One Leg, Slow Breathing
- [ ] Doctor's edit screen and the patient page show it

### Step 6: The other conditions (research → exercises → grid → reading rules)
- [ ] Diabetes (sugar readings; low-sugar risk with some medicines; foot care)
  - [x] Research: `research/DIABETES.md` (2026-10-29)
  - [x] 8 exercises added (2026-10-29): Calf Raise, Seated Knee Straightening, Standing on One Leg, Heel-to-Toe Walk, Side Leg Raise, Seated Marching, Chair Hamstring Stretch, Chin Tuck. New exercise type `balance`; none on the floor; grid rows for all 20 supported conditions (product team), ranked after the existing 17
  - [x] Walking in minutes (1 × 10, up to 45; old plans keep "km"); steps for Walking and Running (2026-10-29)
  - [x] BP 160–179 band also allows balance; high impact read from the exercise table, not a fixed list (2026-10-29)
  - [x] Tests: `backend/tests/test_exercises_2026_10_29.py` (2026-10-29)
  - [x] Re-ranked (`usefulness_rank`) for diabetes, prediabetes, overweight, knee, hip and neck: research-backed exercises first (2026-10-29). Safe still comes before modify whatever the rank
  - [x] Diabetes and prediabetes grid: Wall Sit, Neck Hold, Glute Bridge, Dead Bug "modify" with a breathing note; Running "modify" for prediabetes too (2026-10-29)
  - [x] Decided 2026-11-16: within a plan slot, the usefulness rank decides, "safe" or "modify" alike; a "modify" keeps its caution note (e.g. Seated Knee Straightening now leads the leg slot for knee pain)
  - [x] Floor rule: at age 60+ or BMI 30+, floor exercises are left out of drafts (AI and rules), with a line saying why; the doctor can still add them (2026-10-29)
  - Not ours: medicine rules (eligibility side). Not needed: plan-wide "stop if" list, images
  - [ ] Decide part B (weekly plan, grid changes, medicine rules, new exercises)
  - [ ] Raise the alias gaps (foot ulcer, retinopathy, CKD text) with the colleague
- [ ] Asthma
  - [x] Research: `research/ASTHMA.md`, reviewed once and corrected; 400 patients checked through the API (13 with asthma or COPD) (2026-10-30)
  - [x] 2 exercises added: Belly Breathing, Pursed-lip Breathing (time, chair, light); safe for every supported condition (2026-10-30)
  - [x] New codes: `asthma_controlled` (supported), `asthma_uncontrolled` and `copd` (refer). Asthma aliases → marker `asthma_any`; COPD, COAD, chronic bronchitis, emphysema → `copd` (2026-10-30)
  - [x] Controlled or not (`agent/routing.py`): not controlled with breathlessness or wheeze in a complaint in the last 6 months, an emergency visit, or a latest SpO2 below 94%. No medicines (2026-10-30)
  - [x] "Wheeze / wheezing" added as a warning complaint (2026-10-30)
  - [x] Grid for `asthma_controlled` (27 rows): all safe except Running "modify"; walking, strength, then breathing ranked first (2026-10-30)
  - [x] Tests: `backend/tests/test_asthma.py` (22) (2026-10-30)
  - [ ] Asthma advice for the patient (warm up, stop if wheezy, avoid smoke and cold air) only reaches the draft through Running's note and the condition's notes: decide how condition-level advice should reach the plan
  - [ ] The colleague's flags ("Asthma / COPD not settling") as a "not controlled" signal: needs the API client (step 0)
  - [ ] Try on the 13 asthma patients found (needs the API client)
- [x] Knee, back and hand pain (2026-11-17): research `research/JOINT_AND_BACK_PAIN.md`; built from `PROPOSED_CHANGES_2026-11-17.md`
  - [x] Alias overlap fixed (longest match wins); new aliases for knee, back, nerve root, unnamed joint, hand
  - [x] Back-pain red flags as warning complaints (leg weakness, foot drop, loss of bladder control)
  - [x] New code `hand_pain`; 4 hand exercises (Make a Fist, Finger Spread, Thumb to Fingertips, Towel Squeeze), offered only for hand or wrist pain, in a hand slot that replaces upper-body strength
  - [x] Wall Pelvic Tilt (back) and Mini Squat (knee); back-pain ranks redone; Glute Bridge and Dead Bug "modify" for knee pain (floor)
  - [x] Tests: `backend/tests/test_joint_hand_skin.py`
- [x] Skin (2026-11-17): research `research/SKIN.md`; `skin_condition` (supported, advice in its notes; Running "modify") and `skin_infection` (refer, counts 30 days)
- [x] Thyroid (2026-11-18): research `research/THYROID.md`; `hypothyroid` (supported, 33-row grid, advice in its notes, trial evidence lines) and `hyperthyroid` (refer); a bare "thyroid" (`thyroid_any`) is underactive unless the resting pulse is 90/min or above; tests `backend/tests/test_thyroid.py`
- [ ] Overweight (BMI)
- [ ] Others (PCOD, cholesterol, low mood, tension…)

### Step 7: Checking
- [ ] Dry run on eligible patients: plans vary sensibly with readings
- [ ] Doctors review drafts; edits recorded (`GET /review-summary`)
- [ ] Clinician signs off the exercise library, grid, reading rules and doses

## Decisions log

| Date | Decision |
|---|---|
| 2026-10-28 | Our scope is the exercises, not eligibility |
| 2026-10-28 | New exercises' grid rows written by the product team, like the original 12; the whole grid goes to a clinician together |
| 2026-10-28 | BP bands as in step 4; latest reading within 90 days; stricter of systolic/diastolic; no reading → 140–159 band |
| 2026-10-28 | A BP reading applies to every patient who has one, even without a BP diagnosis; the 140/90 default only when they have BP |
| 2026-10-28 | Sugar, Hb, SpO2 and resting-pulse bands added by the product team (provisional, like the grid). Fasting and random sugar use the same bands; anxiety is a condition (grid), not a reading |
| 2026-11-04 | Lab results count for 6 months (vitals 90 days). The doctor may include older readings (90 days / 6 months / 1 year); an older reading only makes the plan stricter; an old BP counts only if high |
| 2026-11-17 | POC values from our research, not left to the doctor: knee/back/hand/skin aliases, codes, exercises and grid (`PROPOSED_CHANGES_2026-11-17.md`). Hand exercises only for hand or wrist pain |
| 2026-11-16 | Every draft is a balanced plan: walking-type, leg strength, upper-body strength, balance, breathing (cool-down). Within a slot the usefulness rank decides, "safe" or "modify" alike. The AI chooses among each slot's best 3 and explains; the rules set the slots, order and doses (`PENDING_CHANGES.md` 1, options B + D) |
