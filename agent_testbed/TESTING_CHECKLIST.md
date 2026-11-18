# Testing checklist

Which of the 28 test patients are checked and which are left. Full results
and notes are in `AI_TESTING_2026-11-05.md`. Tick a patient here when its row
there is filled in.

Two patients are on two lists (011f5bcd and 035a8857: diabetes and
hypertension): one test covers both.

Before testing: restart the backend so the latest alias rows are loaded.

## AI draft or doctor?

**AI draft (5):** the AI drafted a plan for the doctor to review.

| # | Condition | Patient ID | Severity |
|---|---|---|---|
| 2 | Diabetes | 03cf014c-6e1d-4ad9-8702-2227bb767ee6 | Moderate |
| 8 | Diabetes | 1123000d-f824-4e54-8d9e-2c6823f086c3 | Mild |
| 20 | Asthma | 069d26fe-5bd8-4020-8fbe-5d473d44ce83 | Mild |
| 27 | Asthma | 2913ad8e-3410-4015-8ed6-d57a2d5231c0 | Moderate |
| 28 | Asthma | 30ca6dbf-b0cc-4ebd-acf4-32eca41a1f53 | Moderate |

**Doctor must write (23):** severe, so no AI draft; the doctor writes the plan.

| # | Condition | Patient ID | Main reason |
|---|---|---|---|
| 1 | Asthma | 11c3ad0b-e097-4fe5-92e0-1d3c5f534a3d | BP not under control |
| 3 | Diabetes | 0abd37c0-70d0-4294-b20a-62af9b3258d6 | Tingling |
| 4 | Diabetes | 0aee0bf6-6deb-4a43-b177-b051a7158775 | Heart failure |
| 5 | Diabetes | 0b84894f-30bb-4fb6-b280-d25183ac6ce0 | Heart disease, BP, thyroid |
| 6 | Diabetes | 0c2a35b2-7b0f-4599-9ca5-66909bfe6285 | Tingling in the legs |
| 7 | Diabetes | 0ee85327-dded-4f8b-884e-c7b29efc158f | Dizziness, age 80 |
| 9 | Diabetes + Hypertension | 011f5bcd-45e7-40de-afcd-6e4217b5e0ac | Plantar fasciitis (not listed) |
| 10 | Hypertension | 0575f4e7-5e61-4b90-a5c6-337523d2d91d | Breathlessness while walking |
| 11 | Diabetes | 00d6acb5-e338-49c8-a8cd-8983280a884e | Thyroid (not listed) |
| 12 | Diabetes + Hypertension | 035a8857-bae1-45b2-a6b8-b956f0e58865 | Injury, BP 166/82 |
| 13 | Hypertension | 00e674b6-0e41-40ad-a231-932951ef6e3f | BP 162/90, myelopathy, chest heaviness |
| 14 | Hypertension | 01d3b1b1-47b4-4eae-a1a7-6ac8d22df9a5 | BP 175/94, dizziness at 75 |
| 15 | Hypertension | 021e5f6a-c381-42fd-9427-cd690857ea5a | Chest pain |
| 16 | Hypertension | 02627342-0344-4805-a84e-2bb85daccea1 | BP 146/83 |
| 17 | Hypertension | 03690848-8d41-45d2-b1c1-8ef8c648044e | Many-joint pain, dizziness, tingling |
| 18 | Hypertension | 03b43fae-a95a-45c0-8f61-5eebb84c6f10 | Dizziness with BP |
| 19 | Hypertension | 0428b1a2-6df8-41e5-b351-56f3586184eb | COPD, heart problem (ACS), chest pain |
| 21 | Asthma | 0d23d4bb-8e96-46cb-a847-5591a8df9e3d | Asthma exacerbation, breathlessness, chest pain |
| 22 | Asthma | 15f36e5b-97f7-48e2-b8f0-7f9416992995 | Asthma not under control (SpO2 93%) |
| 23 | Asthma | 1c9068f5-6c8c-4414-b6f2-01e2430d9839 | Chest pain |
| 24 | Asthma | 234c4df2-bb12-4212-a042-bc2c860c069b | Chest pain |
| 25 | Asthma | 25ce6ed8-6a49-4c60-add6-b0ef2dd43c6f | Asthma not under control, many-joint pain |
| 26 | Asthma | 26fde3bc-f28f-4924-8095-1102ff1f5519 | Asthma not under control, neuropathy, tingling |
## Done (28)

| # | Condition | Patient ID | Tested | Plan | Result |
|---|---|---|---|---|---|
| 1 | Asthma | 11c3ad0b-e097-4fe5-92e0-1d3c5f534a3d | 10 Nov | Doctor | Severe: BP not under control |
| 2 | Diabetes | 03cf014c-6e1d-4ad9-8702-2227bb767ee6 | 6 Nov | **AI draft** | Moderate |
| 3 | Diabetes | 0abd37c0-70d0-4294-b20a-62af9b3258d6 | 6 Nov | Doctor | Severe: tingling (and a temperature error) |
| 4 | Diabetes | 0aee0bf6-6deb-4a43-b177-b051a7158775 | 6 Nov | Doctor | Severe: heart failure |
| 5 | Diabetes | 0b84894f-30bb-4fb6-b280-d25183ac6ce0 | 6 Nov | Doctor | Severe: heart disease, BP, thyroid |
| 6 | Diabetes | 0c2a35b2-7b0f-4599-9ca5-66909bfe6285 | 6 Nov | Doctor | Severe: tingling in the legs |
| 7 | Diabetes | 0ee85327-dded-4f8b-884e-c7b29efc158f | 5 Nov | Doctor | Severe: dizziness, age 80 |
| 8 | Diabetes | 1123000d-f824-4e54-8d9e-2c6823f086c3 | 5 Nov | **AI draft** | Mild |
| 9 | Diabetes + Hypertension | 011f5bcd-45e7-40de-afcd-6e4217b5e0ac | 10 Nov | Doctor | Severe: plantar fasciitis (not listed) |
| 10 | Hypertension | 0575f4e7-5e61-4b90-a5c6-337523d2d91d | 10 Nov | Doctor | Severe: breathlessness while walking |
| 11 | Diabetes | 00d6acb5-e338-49c8-a8cd-8983280a884e | 10 Nov | Doctor | Severe: thyroid (not listed) |
| 12 | Diabetes + Hypertension | 035a8857-bae1-45b2-a6b8-b956f0e58865 | 10 Nov | Doctor | Severe: injury, BP 166/82 not under control |
| 13 | Hypertension | 00e674b6-0e41-40ad-a231-932951ef6e3f | 10 Nov | Doctor | Severe: BP 162/90, myelopathy, chest heaviness |
| 14 | Hypertension | 01d3b1b1-47b4-4eae-a1a7-6ac8d22df9a5 | 10 Nov | Doctor | Severe: BP 175/94, dizziness at 75 |
| 15 | Hypertension | 021e5f6a-c381-42fd-9427-cd690857ea5a | 10 Nov | Doctor | Severe: chest pain (and a temperature error; still severe without it) |
| 16 | Hypertension | 02627342-0344-4805-a84e-2bb85daccea1 | 10 Nov | Doctor | Severe: BP 146/83 (and a temperature error; still severe without it) |
| 17 | Hypertension | 03690848-8d41-45d2-b1c1-8ef8c648044e | 10 Nov | Doctor | Severe: many-joint pain, dizziness, tingling (and a temperature error; still severe without it) |
| 18 | Hypertension | 03b43fae-a95a-45c0-8f61-5eebb84c6f10 | 10 Nov | Doctor | Severe: dizziness with BP |
| 19 | Hypertension | 0428b1a2-6df8-41e5-b351-56f3586184eb | 10 Nov | Doctor | Severe: COPD, heart problem (ACS), many-joint pain, chest pain (alias gaps fixed and retested) |
| 20 | Asthma | 069d26fe-5bd8-4020-8fbe-5d473d44ce83 | 10 Nov | **AI draft** | Mild (4 exercises, all safe) |
| 21 | Asthma | 0d23d4bb-8e96-46cb-a847-5591a8df9e3d | 10 Nov | Doctor | Severe: asthma exacerbation, breathlessness, chest pain (screen bug found and fixed) |
| 22 | Asthma | 15f36e5b-97f7-48e2-b8f0-7f9416992995 | 10 Nov | Doctor | Severe: asthma not under control (SpO2 93%) |
| 23 | Asthma | 1c9068f5-6c8c-4414-b6f2-01e2430d9839 | 10 Nov | Doctor | Severe: chest pain (no doctor on his visit: pick any doctor, then paste the id) |
| 24 | Asthma | 234c4df2-bb12-4212-a042-bc2c860c069b | 10 Nov | Doctor | Severe: chest pain |
| 25 | Asthma | 25ce6ed8-6a49-4c60-add6-b0ef2dd43c6f | 10 Nov | Doctor | Severe: asthma not under control (breathlessness, exacerbation), many-joint pain |
| 26 | Asthma | 26fde3bc-f28f-4924-8095-1102ff1f5519 | 10 Nov | Doctor | Severe: asthma not under control, breathlessness, diabetic neuropathy, tingling, joint pain (warning-list gap fixed and retested) |
| 27 | Asthma | 2913ad8e-3410-4015-8ed6-d57a2d5231c0 | 10 Nov | **AI draft** | Moderate (pulse rule applied). Flag: chest pain and RA only in the doctor's note |
| 28 | Asthma | 30ca6dbf-b0cc-4ebd-acf4-32eca41a1f53 | 10 Nov | **AI draft** | Moderate (age 60+ rules applied) |

## To test (0)

All 28 tested (10 Nov 2026). Results summary: the "Summary" section of `AI_TESTING_2026-11-05.md`.

## Round 2: frequent visitors (13 Nov 2026)

5 patients from the colleague's dashboard (`patient_dashboard.html`), 6 to
23 visits each. They test today's changes: the rules read **every** visit,
and each finding and reading counts only inside its time window
(`backend/data/time_windows.csv`: injury 90 days, complaints 183, SpO2 and
pulse 30, BP and sugar 90, Hb 180).

This list replaces the 11 patients first picked for Round 2. Those are still
the examples for low BP, underweight and kidney disease in
`QUESTIONS_FOR_DOCTOR.md`.

**Before testing:** push today's work and let Render restart (or restart the
backend locally), so the time windows and the all-visits change are loaded.

**After 17 Nov (joint, hand and skin changes, `PROPOSED_CHANGES_2026-11-17.md`):** restart the backend, then
retest #31–33 and test #32. Expected now: #31 still doctor (the 94 °F critical flags; rule kept as is, decided 17 Nov) with
only "Skin problem" (no BP: KNOWN_ISSUES.md #14); #32 still doctor (tingling; multiple joint pain) with hand pain found; #33 still an AI draft,
now with "Skin problem" and its advice.

"Expected" is our reading of the record (13 Nov), not a test result. Fill in
"Result" when tested.

| # | Patient ID | Who | Visits | What to look for | Expected | Tested | Result |
|---|---|---|---|---|---|---|---|
| 29 | bd8b445c-bc70-4c42-ba93-8af0b7da478b | 50 M, diabetes + BP, BMI 30.8 | 20 | **Shoulder pain** in complaints up to 28 Sep; neck spondylosis, back pain; a fall on 18 Jun (148 days ago) should show as **"Not counted, too old"**; latest BP 135/76 | Doctor (shoulder pain: not listed) | 16 Nov | **Doctor**, as expected (shoulder pain → not listed). Matches the colleague's dashboard. Six fixes made while testing: see "Round 2 results" below |
| 30 | 016e4c77-97b3-415f-a621-e15a8813d31d | 40 F, diabetes + BP (first written 6 Aug) | 6 | **Tingling in the hand** (10 Jul, within 6 months); eczema, shingles; temperature data errors | Doctor (tingling) | 16 Nov | **Doctor**, as expected (tingling, 10 Jul). Matches the colleague's dashboard. Three fixes: see "Round 2 results" below |
| 31 | 0017c9d8-6747-4036-ade6-915883b5b123 | 36 F, only eczema | 8 | Temperatures of 94 °F at 3 of the last 5 visits (data errors); pulse 103–109 and SpO2 94 in Jul/Aug are **older than 30 days**, so they shouldn't limit the plan; latest pulse 96, SpO2 99; the readings line says "none recent for …" with each window | Doctor only if a temperature flag is critical; else **AI draft** | | |
| 32 | bdbdc1f3-052a-4f33-add9-854e2cd190e7 | 46 F, no long-term condition | 23 | **Tingling at visits 10, 11 and 13 of 23**, which is **outside the latest 10**: this is the all-visits fix; knee arthritis, low back ache, "multiple joint pain", shoulder and hand pain | Doctor (tingling, joint pain) | | |
| 33 | 6959e408-f855-4f21-82b7-87a346012529 | 57 M, BP, BMI 31.2 | 20 | Mostly fungal skin infection; latest BP 133/87 (150/93 on 29 Aug); leg muscle pain | **AI draft**: walking first, no floor or high-impact exercises (BMI 30+), no BP band | 16 Nov | **AI draft (moderate)**, as expected. Two open points: see "Round 2 results" below |

## Round 2 results

### #29 · bd8b445c (50 M, diabetes + BP) · tested 16 Nov 2026

Compared with the colleague's dashboard (`patient_dashboard.html`, Patient 1)
and her API. Tested about 8 times while fixing.

**Result: Doctor must write the plan (severe).** The only reason is
shoulder pain ("Lt. shoulder pain", 28 Sep complaint, and earlier
"Shoulder pain" / "Joint pain" diagnoses): we have no shoulder exercises, so
it is `other_unlisted`. Without it he would get an AI draft (BP 135/76 is
below the 140/90 band).

**Matches the colleague's dashboard**
- 50 M, 20 visits (19 May → 1 Oct), BMI 30.8
- Diabetes and BP (recorded and in diagnoses), neck spondylosis, low back
  pain, knee pain, hip pain
- 1 missed follow-up (11 Oct). Her dashboard file says 2; her live API now
  marks the 27 Aug one "attended off date", so 1 is right
- Latest prescription: 7 medicines (after fix 2 below)

**Differences, by design**
- BP: we say "under control" (latest reading not flagged high: exercise
  safety); she flags "above the 130/80 target" (treatment target with
  diabetes). Both right.
- Diabetes: we say "control not known" (no sugar reading in 90 days); her
  HbA1c 7.6 % comes from undated reports we can't place in time. The doctor
  sees her flag.
- The fall on 18 Jun is not shown as "Not counted, too old": there is no
  alias for "fall", so it never became a finding. Past the 90-day injury
  window anyway.

**Fixed while testing (16 Nov)**
1. **AI failure now shown:** a warning on the assessment when the AI check
   didn't run. Today's cause: the OpenRouter key had stopped working (401);
   replaced.
2. **Current medicines:** the API's `ongoing_medicines` listed 28 (every
   medicine ever, incl. stopped NSAIDs and Amlodipine). Now read from the
   timeline: the latest prescription, 7 medicines with doses; each visit in
   Visit history shows its own.
3. **No "controlled" in the AI's text:** removed in code from its summary and
   concerns (the rules decide control).
4. **Clinic flags in the concerns:** the colleague's high and medium flags
   are shown as "Clinic flag: …" lines with their dates, written by our code.
   Medicine flags are left out, and past flags older than 183 days
   (`time_windows.csv`, row `clinic_flag`).
5. **Medicines and exercise:** the AI sees prescriptions from the last 90
   days (`time_windows.csv`, row `medicine`) and writes one "Medicine: …"
   line per medicine that changes exercise (Glimepiride: low sugar;
   Telmisartan: dizziness on standing). It never suggests medicine changes.
   No rule uses medicines.
6. **Evidence tidied:** the AI's raw field names reworded
   ("diagnosis_provisional" → "diagnosis"), and its repeats of the rules'
   lines dropped (e.g. BMI 30.8 shown once).

**Final screen (16 Nov):** severe; 8 conditions; concerns: 2 from the AI
(general weakness; blurred vision and swelling in past visits), 3 medicine
lines, 8 clinic flag lines with dates; missing: recent sugar reading.

**Still open**
- **Metformin:** the AI wrote "risk of low sugar" for Metformin; on its own it
  rarely causes it (the risk here is Glimepiride). Left as a model limit.
- **Wrong AI evidence:** back pain got the AI quote "K/C/O-HTN-DM, general
  weekness, acidity", which doesn't mention back pain (the check only confirms
  a quote exists). No effect on the decision. Proposed: hide the AI's
  evidence for conditions the rules already found.
- **Blurred vision with diabetes** isn't one of our warning complaints (the
  colleague flags it high). Question for the doctor: should it stop an AI
  draft, or stay a concern?
- **AI varies run to run:** body area and which conditions it agrees with
  change between runs; the rules' result doesn't.
- Not yet committed or pushed to Render.

### #30 · 016e4c77 (40 F, diabetes + BP) · tested 16 Nov 2026

Compared with the colleague's dashboard (Patient 2) and her API.

**Result: Doctor must write the plan (severe).** Reason: "tingling sensation
on hand" in the 10 Jul complaint (129 days ago, inside the 183-day window).
Her dashboard flags the same ("Possible neuropathic symptoms").

**Matches the colleague's dashboard**
- 40 F, 6 visits (10 Jul → 6 Aug); no recorded long-term conditions:
  diabetes and BP come from the 6 Aug diagnosis "T2dm, htn" and the
  complaints "KCO HTN" / "KCO DM"
- Labs 6 Aug: HbA1c 7.6 %, triglycerides and VLDL high, white cells 11,500,
  creatinine normal, Hb 12.3; BMI 27.4; weight 70 → 65 kg in 5 days
- Current medicines (6 Aug): the same 6, plus "Vasaline 0-0-0", which she
  leaves out (no dose)
- 0 missed follow-ups: her dashboard file says 1 (16 Aug); her live API now
  marks it "attended off date"
- Clinic flags: the 7 non-medicine flags shown with dates; the steroid flags
  (medicine) left out

**By design**
- Readings: only Hb 12.3 counts (180-day window). BP, sugar, SpO2 and pulse
  are from 6 Aug, 102 days ago: "none recent". As a BP patient with no BP in
  90 days she would get the cautious 140/90 band in a draft.
- No "Medicine:" lines: her latest prescription (6 Aug, Glimepiride and
  Amlodipine started) is 102 days old, past the 90-day medicine window.
  Kept at 90 days; asked in `QUESTIONS_FOR_DOCTOR.md` (section 2, question 6).
- "Overweight" was added by the AI at BMI 27.4 (our rule: 30). Example added
  to `QUESTIONS_FOR_DOCTOR.md` 1a (which BMI cut-off).

**Fixed while testing (16 Nov)**
1. **Sugar lab names:** her reports say "Glucose" and "BLOOD SUGAR RANDOM",
   which the reading rules didn't read. Added (and "Blood Sugar Fasting",
   "Fasting Blood Glucose"…), mg/dL only. No change for her (102 days old).
2. **AI summary line from the record only:** it wrote "type 2 diabetes,
   obesity, and dyslipidemia", taking "dyslipidaemia" from her flag
   ("pattern with no matching diagnosis"), and left out the tingling. Now told
   to write it from diagnoses, complaints and readings only, name warning
   symptoms, and not repeat clinic flags in its own concerns.
   Retested: the summary now names the tingling and no longer says
   "dyslipidemia", but still says "high cholesterol" (triglycerides only) and
   "elevated blood pressure" (from her API's flags on 122/62). Left as a model
   limit, like the AI concerns that still repeat clinic flags.
3. **"Under control" from an old reading:** after fix 1, the 6 Aug sugar
   (128.4, 102 days old) made it "Sugar under control", next to "none recent
   for sugar". Now an old **normal** reading means "control not known (no
   recent … reading)", and an old **high** one still means "not under
   control" (doctor). Same exercise rules either way. Her BP (6 Aug, 122/62)
   also becomes "control not known".

**Still open**
- Whether an old **high** reading should also stop counting: question 2 in
  `QUESTIONS_FOR_DOCTOR.md` section 2.
- The lab results panel lists each result twice (the same report on both
  6 Aug visits). Cosmetic.


## What to note for each patient

- Severity, and the reasons if severe
- Conditions found, and whether BP, diabetes or asthma is under control
- The draft: AI, rules or "doctor must write"; the exercises and doses
- Readings used, and any warnings
- For a temperature-error patient: would it still be severe without that reason?
- Round 2 only:
  - Findings from older visits (beyond the latest 10) are found, e.g. tingling at visit 13 of 23 (#32)
  - Anything past its window shows as "Not counted, too old: …", not as a reason (#29)
  - The readings line shows each reading's own window, e.g. "none recent for SpO2 (30 days)" (#31)
  - Does the result match the colleague's dashboard for the same patient?

### #33 · 6959e408 (57 M, BP, BMI 31.2) · tested 16 Nov 2026

Compared with the colleague's dashboard (Patient 5) and her API.

**Result: AI draft (moderate), as expected.** Walking (1 × 10 min), Slow
Breathing (1 × 5 min), Calf Raise (2 × 8), Seated Knee Straightening (2 × 8
each side), Chin Tuck (2 × 5).

**Right by our rules**
- BP 133/87 (10 Oct) is below 140/90: no BP band. The 150/93 on 29 Aug is
  not the latest reading. Flagged "elevated" only, so "BP under control".
- BMI 31.2 (overweight): Running and the 4 floor exercises left out; all 5
  chosen are standing or seated. Age 57: normal starting doses.
- SpO2 and pulse (10 Oct, 37 days) are past their 30-day window: "none
  recent". No "Medicine:" lines: the latest prescription (10 Oct) is
  antifungals and cetirizine only.
- 2 missed follow-ups (25 Jun, 20 Oct): her dashboard file says 4; her live
  API now says 2.
- The AI summary is accurate (BP, obesity, recurrent fungal infection).

**Open**
1. **"No Hypertension medicine prescribed since #13" is not shown.** His BP
   medicines (Amlodipine, Telmisartan) were last prescribed on 6 Aug; since
   then BP 150/93 (29 Aug) and 130/90 (17 Sep). Her API marks the flag
   `kind: medication`, so our code leaves it out of the "Clinic flag:" lines
   (medicine flags are dropped). Unlike the NSAID flags it is about
   untreated BP, which matters before exercise. The doctor sees it in the
   side panel only. Idea: keep dropping medicine flags, but show the
   "no … medicine prescribed since" ones (treatment gap). Not decided.
   (The plan is still safe by our rules: latest BP under 140/90.)
2. **Generic exercise choice.** He has no knee or neck problem but got
   Seated Knee Straightening and Chin Tuck; Wall Push-up (offered 5th) and
   Sit to Stand (BP research) would fit better. Causes: the AI isn't told
   the allowed list is ordered most useful first; Sit to Stand is "modify"
   for obesity (a mild "sturdy chair" note), so it sits 20th, behind every
   "safe" exercise; nothing asks for a balanced plan. Same as
   `KNOWN_ISSUES.md` #10. Options:
   - A. One prompt line: the list is ordered most useful first, prefer the
     top ones (quick; still the model's choice).
   - B. A balanced mix in code: walking first, then 1 breathing, 2 strength
     (upper and lower body), 1 balance or mobility, each the top-ranked
     allowed one of its type; the AI only orders and explains. This is
     `EXERCISE_FIT_TRACKER.md` step 5. **Recommended**, with D.
   - C. A body-part tag per exercise (knee, neck…) in
     `activity_taxonomy.csv`, offered only for that problem (data work).
   - D. A mild "modify" note keeps the exercise's rank (the open decision
     in `EXERCISE_FIT_TRACKER.md`).
   **Built 16 Nov (B + D) and retested:** AI draft, Walking (1 × 10 min),
   Sit to Stand (2 × 5, note: sturdy chair with armrests), Wall Push-up
   (2 × 5), Standing on One Leg (2 × 10 s each side), Slow Breathing
   (1 × 5 min). A first retest fell back to the rules draft because the AI
   wrote "walking" (a name) instead of "walk"; names are now accepted.
   The AI's instructions name walking (told not to name exercises):
   harmless.
3. As before (model limit): the AI's two concerns repeat clinic flags. A
   medicine-named flag still gets through ("Repeated oral azole antifungal
   without liver tests"): her API marks it `followup`, not `medication`.
