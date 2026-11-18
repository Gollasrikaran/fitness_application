# Questions for the doctor (clinical review)

Things we need a doctor to decide before the agent is used for real. Each
one says what the app does today, an example patient from our testing, and
what we need to know. Collected from testing (`AI_TESTING_2026-11-05.md`)
and `KNOWN_ISSUES.md`. Started 2026-11-10; add to it as testing goes on.

All our rules are still marked "not clinically reviewed". A doctor approves
every plan, and nothing reaches a patient without that.

## 1. Body weight (BMI)

### 1a. Overweight
- **Today:** BMI 30 or above counts as "Overweight". Then no high-impact
  exercises (e.g. running) and no exercises on the floor.
- **Examples:** 0abd37c0 (BMI 28.8) and 0428b1a2 (BMI 27.1): our rule
  didn't call them overweight, but the AI did. Also 016e4c77 (BMI 27.4,
  2026-11-16): the same, and the colleague's API calls her "obese (Asian
  Indian cut-off)".
- **Question:** Indian guidelines use lower cut-offs than 30 (overweight
  from about 23, obese from about 25). Which cut-off should we use?

### 1b. Underweight
- **Today:** no rule at all.
- **Examples:** 01d3b1b1, 75 years old, BMI 18.3; 02627342, 68 years old,
  BMI 17.2.
- More examples (2026-11-13): 0e9a6d9b (65, BMI 17.6), f9c3432c (73, BMI
  17.6), ea9b6faa (71, BMI 17.3), 368015e7 (78, BMI 18.2).
- **Questions:** Should underweight (below 18.5?) change the plan? For
  example lighter exercises, more care at older age (falls, weakness), or
  a doctor writes the plan?
- **Built 2026-11-13 as a provisional rule, needs your sign-off (sources in `research/SOURCES_LOW_BP_UNDERWEIGHT_CKD.md`):**
  - BMI 16–18.4: a concern for the doctor ("Underweight: check for weight
    loss or illness"), nothing vigorous, strength and balance exercises
    first. Not a stop on its own: no source says underweight alone should
    stop exercise, and light strength work is what's advised.
  - BMI below 16 (WHO "severe thinness"): a doctor writes the plan.
  - Underweight at 60+: the age rules already apply (no floor exercises,
    doses one step lower); add the concern line.
  - Which cut-off: WHO uses 18.5; the 2009 Indian consensus starts "normal"
    at 18.

## 2. How far back the agent looks (time windows)

All the numbers below are in `backend/data/time_windows.csv` (POC values
set 2026-11-13, to adjust at the meeting: change a number and restart).

| What | Today |
|---|---|
| Readings that limit the plan | Each reading its own window (2026-11-13): **SpO2 and pulse 30 days** (they change within days, e.g. with a fever), **BP and sugar 90 days**, **Hb 180 days** (changes slowly). A vital or a lab report alike. The doctor can include up to 6 months or 1 year (older readings only make the plan stricter; an old BP counts only if 140/90 or above) |
| Whether BP or sugar is "under control" | The latest reading. Since 2026-11-16: if it is older than its window (90 days), a normal reading no longer means "under control" (shown as "control not known"), while a high one still means "not under control" |
| Whether asthma is "under control" (SpO2 below 94%) | The latest SpO2 in the last 10 visits, however old (unchanged) |
| Warning complaints (chest pain, dizziness…) | Last 6 months |
| Diagnoses | Every visit; fresh injury, surgery and sprain 90 days, pregnancy 365 days, the rest however old |
| BP patient with no reading in 90 days | Treated as 140–159/90–99 (cautious: fewer exercises) |
| Medicines the AI sees (since 2026-11-16) | Prescriptions from the last **90 days**: the AI notes how they affect exercise (e.g. sugar tablets: low sugar), never suggests changes. No rule uses medicines |
| The colleague's clinic flags shown to the doctor (since 2026-11-16) | Current and undated flags always; past flags from the last **183 days**; medicine flags never |

**Questions:**
1. Are these reading windows right (SpO2 and pulse 30 days, BP and sugar
   90, Hb 180)? A shorter window is less strict: an older low SpO2 or fast
   pulse no longer limits the plan (the doctor still sees it on screen). A
   BP patient with no BP reading in 90 days gets the cautious default.
2. Should "under control" (BP, sugar, and asthma's SpO2) use the same
   windows as the plan limits? Today one patient
   (11c3ad0b) showed "no readings in the last 90 days" next to "BP not under
   control" from a reading 116 days old. We left this as is for now, since
   real data will have recent readings.
   **Partly decided 2026-11-16:** old good news no longer counts, old bad
   news still does. 016e4c77 showed "Sugar under control" from a normal
   sugar 102 days old, next to "none recent for sugar"; it now says
   "Diabetes, control not known (no recent sugar reading)". An old high BP
   still sends the patient to a doctor (to keep it safe). Still to confirm
   with you: should an old **high** reading also stop counting?
3. How long should these count: **injury** and **surgery** (3 months?),
   **pregnancy** (up to 12 months after delivery?)? Example: 035a8857, an
   injury from 105 days ago still counted as "fresh".
   **POC values set 2026-11-13, to adjust at the meeting** (in
   `backend/data/time_windows.csv`; change a number and restart):
   fresh injury 90 days, recent surgery 90 days, pregnancy 365 days, sprain
   90 days; complaints and warning complaints 183 days (as before); every
   other diagnosis counts however old. Anything left out as too old is still
   shown to the doctor ("Not counted, too old: …"). 035a8857's injury no
   longer counts (his high BP still sends him to a doctor). Sources in
   `research/SOURCES_LOW_BP_UNDERWEIGHT_CKD.md`.
   Also since 2026-11-13: the rules read **every** visit, not just the
   latest 10 (0e9a6d9b: tingling at visits 17 and 19 of 22 was missed
   before). The AI still reads the latest 10.
4. Is 6 months right for lab results?
5. Should **dizziness** count for less than 6 months (it often passes, e.g.
   with an infection)?
6. **Medicines: is 90 days from the prescription right?** Example: 016e4c77
   (2026-11-16) was started on Glimepiride (sugar tablet) and Amlodipine (BP)
   on 6 Aug, written for 10 days, and has not visited since. At 102 days the
   prescription is too old, so the doctor gets no note about low sugar during
   exercise. Diabetes and BP medicines are usually taken for years. Should
   they count longer than other medicines (e.g. painkillers, antibiotics),
   or is 90 days for all right? Kept at 90 days for all until you decide.

## 3. Conditions we don't cover yet

- **Today:** a condition we have no exercises for sends the patient to the
  doctor ("doctor must write the plan").
- **Seen most in testing:**
  - **Thyroid** (hypo / hyper): 00d6acb5, 0b84894f
  - **Plantar fasciitis / heel pain**: 011f5bcd. The doctor's note there
    advised standing on the toes (our Calf Raise) and soft footwear.
- Others that do the same: shoulder pain, pain in many joints, vertigo,
  anaemia.
- **Kidney disease (CKD)** (added 2026-11-13): 7673431d, 67, diagnosis "HT
  with CKD". Before, CKD was caught only when recorded in the formal
  condition list, not in a diagnosis. **Done:** "ckd", "chronic kidney
  disease", "kidney disease" and "renal failure" now send the patient to a
  doctor (stricter only). KDIGO 2024 recommends 150 minutes a week of
  moderate activity for people with CKD, so later we could cover stable CKD
  (no breath-holding, effort judged by feel; dialysis still to a doctor).
  Should we research it?
- **Questions:** Can a patient with thyroid that is treated and stable get
  a normal plan? Which exercises suit heel pain (calf raises, calf and foot
  stretches)? Which of these conditions should we research next?

## 4. Symptoms that stop an AI plan (warning complaints)

- **Dizziness (decided 5 Nov, needs sign-off):** stops the AI plan only at
  age 60+, or with BP, diabetes or a heart condition. Otherwise it's a note
  for the doctor. Example: 01d3b1b1 (75, BP 175/94) was stopped; right?
- **Numbness / tingling:** stops the AI plan for everyone today. Examples:
  0abd37c0, 0c2a35b2 (diabetics with tingling in the legs). Should tingling
  alone always stop it, or only with diabetes?
- **Blurred vision with diabetes (added 16 Nov):** not one of our warning
  complaints today, so it doesn't stop an AI plan. The colleague's API flags
  it high ("Visual symptoms with diabetes"); the doctor now sees that flag
  in the assessment. Example: bd8b445c ("blurr vission", 19 and 29 May).
  It can mean eye damage from diabetes, which matters for straining and
  vigorous exercise. Should it stop an AI plan, or stay a note?
- **Is the list complete?** Chest pain, breathlessness, wheeze, dizziness,
  fainting, palpitations, numbness, seizure.

## 5. Blood pressure and sugar

1. **High BP reading but no BP diagnosis.** Today this depends on whether
   the AI notices the reading: 11c3ad0b (128/94) went to the doctor, 03cf014c
   (131/90) got a plan with BP limits. Should a high reading alone always
   send the patient to a doctor?
2. **BP limits (sign-off):** below 140/90 nothing extra; 140–159 / 90–99
   no holding exercises and nothing vigorous; 160–179 / 100–109 only
   walking, breathing, balance and gentle movement; 180/110 or above no
   plan, the doctor decides.
3. **Diabetes with no sugar reading** (most of our diabetics): shown as
   "control not known". Should these patients also get a cautious default
   like BP (e.g. nothing vigorous)?
4. **Low BP:** we have limits only for high BP. Example: 03b43fae, a
   hypertension patient whose doctor wrote "hypotension, dizziness" (BP
   110/87). Should low BP (e.g. below 90/60) or dizziness on standing limit
   the plan? Another example (2026-11-13): 343bdbdc, 81, hypertension and
   asthma/COPD, latest BP 85/63 flagged `BP_SYS_LOW`. Today the clinic's LOW
   flags are ignored and there is no low-BP reading band.
   **Built 2026-11-13 as a provisional rule, needs your sign-off (sources in `research/SOURCES_LOW_BP_UNDERWEIGHT_CKD.md`):**
   - BP below 90/60 with no symptoms: not a stop on its own (low BP is
     usually only a concern with symptoms). Leave out floor exercises
     (getting up from the floor drops BP most) and vigorous exercise; tell
     the patient to rise slowly and drink water.
   - Low BP with dizziness or fainting: a doctor writes the plan (fainting
     already stops everyone; dizziness at 60+ or with BP).
   - The clinic's `BP_SYS_LOW` / `BP_DIA_LOW` flags and a diagnosis of
     "hypotension" shown to the doctor as a concern.
5. **Sugar, Hb, SpO2 and pulse limits (sign-off):** e.g. sugar 300+ or
   below 70, Hb below 8, SpO2 below 92, pulse 120+ means no plan.

## 6. Other

1. **Referral to a higher centre or specialist:** not a reason to stop the
   AI plan today (only emergency visits are). Should it be? Examples:
   0ee85327, 0b84894f.
2. **Wrong temperatures** (e.g. 34.6 typed in the °F field) are flagged
   "critical" by the clinic and send patients to the doctor (021e5f6a,
   02627342, 03690848). Should temperature affect exercise plans at all?
   All three had another real reason too (chest pain; high BP; dizziness,
   tingling and many-joint pain), so the result didn't change.
3. **Warning signs written only in doctors' notes.** Our rules read the
   complaint and diagnosis fields, not the notes, because a note can also
   say "no chest pain". Example: 2913ad8e, complaint "Cough and vomiting",
   note "Chest pain and vomiting and nausea. K/c/o RA on treatment": she got
   an AI draft. Should the notes be checked for warning words (chest pain,
   breathlessness…), at least to show a warning on the draft?
4. **Doctors' notes with exercise advice** (e.g. "VMO and quadriceps
   strengthening", "stand on toes"): would it help to show these next to the
   plan editor?
5. **Sign-off of the whole library:** the 27 exercises, their starting and
   maximum doses, and the safety grid (which exercise is safe / with care /
   avoid for each condition).
