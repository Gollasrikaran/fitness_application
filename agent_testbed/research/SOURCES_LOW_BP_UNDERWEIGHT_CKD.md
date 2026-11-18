# Sources: low BP, underweight, kidney disease (CKD) and time windows

13 November 2026. The sources behind our proposed rules for three gaps found
while checking 11 frequent-visit patients from a colleague. The proposals
themselves are in `QUESTIONS_FOR_DOCTOR.md` (sections 1b, 3 and 5.4). None
of them are clinically reviewed yet.

**How sure we are:** most of these came from web searches. Some are
patient-facing pages or secondary summaries, not the original guideline. A
clinician should check the ones marked "check the original" before sign-off.

## 1. Low BP

| What we took | Source | Note |
|---|---|---|
| Low BP is usually below 90/60 | [Mayo Clinic: Low blood pressure](https://www.mayoclinic.org/diseases-conditions/low-blood-pressure/symptoms-causes/syc-20355465) | |
| It is usually only a concern with symptoms (dizziness, fainting) or a sudden drop; a 20 mmHg change can cause dizziness | Mayo Clinic, as above | |
| No number is "too low" without symptoms (said to be the American Heart Association's view) | [SingleCare: low blood pressure](https://www.singlecare.com/blog/low-blood-pressure/), [Next Avenue](https://www.nextavenue.org/what-you-need-to-know-about-low-blood-pressure/) | Second-hand: check the original on heart.org |
| Rise slowly from lying or sitting, drink enough, avoid long standing; regular moderate exercise helps | [MSD Manual: Orthostatic hypotension](https://www.msdmanuals.com/professional/cardiovascular-disorders/symptoms-of-cardiovascular-disorders/orthostatic-hypotension) | Exercise can also bring on symptoms, so start gently |
| Regular physical activity in middle age linked to a smaller BP drop on standing | [PMC: activity and orthostatic BP in older adults (2023)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10673924/) | One study |
| Pre-exercise screening in general (ACSM-based) | [UH lab manual: pre-test screening](https://uhlibraries.pressbooks.pub/kin4370labmanual/chapter/pre-test-screening-and-assessment/) | We found no ACSM cut-off for low resting BP: check the original ACSM guidelines |

## 2. Underweight

| What we took | Source | Note |
|---|---|---|
| Underweight is a BMI below 18.5 (WHO); below 16 is "severe thinness" | WHO BMI classification | Standard definition |
| Indian consensus (2009): normal 18–22.9, overweight 23–24.9, obese 25+ | [Data for India: measuring obesity](https://www.dataforindia.com/measuring-obesity/), [PMC: BMI cut-offs in India](https://pmc.ncbi.nlm.nih.gov/articles/PMC5903015), [CMC Vellore: revised definition of obesity in Asian Indians (2025)](https://www.cmcendovellore.org/pub/2025/revised-definition-of-obesity-in-asian-indians-living-in-india.pdf) | Original: Misra et al., JAPI 2009;57:163–170. Check the original for its underweight cut-off |
| Older adults: screen for malnutrition and muscle loss whatever the BMI; strength training at least twice a week | [ASPEN: sarcopenic obesity in older adults](https://nutritioncare.org/wp-content/uploads/2026/07/Sarcopenic-Obesity-Older-Adults.pdf) | The strongest source here |
| Low BMI linked to frailty and illness; frail people should do light strength, balance, flexibility and endurance work | [Nebraska nutrition text: obesity, sarcopenia and frailty](https://pressbooks.nebraska.edu/nutr251/chapter/obesity-sarcopenia-and-frailty/) | Teaching text |
| The best BMI after 65 may be higher than for younger adults | [The Geriatric Dietitian: BMI in the elderly](https://thegeriatricdietitian.com/?p=1177) | Educational page |
| Unplanned weight loss in older age is a warning sign | [AARP: gaining weight safely](https://www.aarp.org/health/healthy-living/info-2023/how-to-gain-weight-safely) | News/advice page |

No source we found says underweight alone should stop exercise.

## 3. Kidney disease (CKD)

| What we took | Source | Note |
|---|---|---|
| KDIGO 2024: people with CKD should do moderate activity for at least 150 minutes a week, or as their heart and fitness allow (a weak recommendation) | [NephJC: KDIGO 2024 CKD guideline, part 2](https://www.nephjc.com/news/kdigo-ckd-part2), [Guideline Central: KDIGO CKD](https://www.guidelinecentral.com/guideline/25092) | Check the original: Kidney International 2024;105(4S):S117–S314 |
| The guideline gives little practical detail | [Italian commentary on KDIGO 2024](https://link.springer.com/10.1007/s40620-024-02049-9) | |
| Exercise is safe with CKD; no straining or breath-holding when lifting; judge effort by feel, not pulse; on dialysis, no weight on the fistula arm | [ACSM Exercise is Medicine: being active with CKD](https://acsm.org/wp-content/uploads/EIM_Being-Active-When-You-Have-Chronic-Kidney-Disease_Flyer_English.pdf) | Patient flyer |
| Stop if dizzy or short of breath; avoid when very fluid-overloaded; ask the care team first | [National Kidney Foundation: safe exercises for CKD and dialysis](https://www.kidney.org/news-stories/15-safe-exercises-ckd-dialysis-and-post-transplant-patients) | Patient page |
| The usual reasons not to exercise still apply; exercise on non-dialysis days | [RCN: chronic kidney disease factsheet](https://scadmin.rcn.org.uk/-/media/Royal-College-Of-Nursing/Documents/Clinical-Topics/Public-Health/M2M/Chronic-kidney.pdf) | 2019 |

## 4. Time windows: how long an injury, surgery or pregnancy counts

POC values in `backend/data/time_windows.csv` (added 2026-11-13), to adjust
with the doctor. No formal guideline gives one number; these are the usual
recovery milestones.

| Window | What we took | Source | Note |
|---|---|---|---|
| Fresh injury, sprain: 90 days | Soft tissue repairs in weeks 1–6 and keeps remodelling for months; bad (grade III) sprains take about 8–12 weeks | [NHS Leeds: soft tissue injuries](https://www.leedsth.nhs.uk/patients/resources/soft-tissue-injuries-of-the-ankle/), [NHS Leeds Community: return to activity after injury](https://leedscommunityhealthcare.nhs.uk/our-services-a-z/musculoskeletal-msk/return-to-activity-or-sport-after-injury/), [VCU: lateral ankle sprains](https://recwell.vcu.edu/play/sport-clubs/athletic-training/lateral-ankle-sprains-article/), [Sanford Health: ankle sprain rehab](https://www.sanfordhealth.org/-/media/org/files/medical-professionals/resources-and-education/014000-01095-flyer-ankle-sprain-rehabilitation-pt-guideline.pdf) | Fractures were not covered by what we found: check with the doctor |
| Recent surgery: 90 days | Light activity from about 6 weeks, heavy lifting and core work from about 12 weeks after major (open) surgery; keyhole surgery is quicker | [NHS Sussex: physiotherapy after abdominal surgery](https://www.uhsussex.nhs.uk/resources/physiotherapy-advice-after-abdominal-surgery/), [Swedish: returning to activity after abdominal surgery](https://blog.swedish.org/lifestyle/returning-to-normal-activity-after-abdominal-surgery) | Patient leaflets; depends on the operation |
| Pregnancy: 365 days | A pregnancy diagnosed early can run about 34 more weeks; ACOG's postpartum care runs to 12 weeks, and strenuous exercise usually waits until about 12 weeks after the birth | [Peloton: when can I start exercising after birth (ACOG summary)](https://www.onepeloton.com/en-CA/blog/when-can-i-start-exercising-after-birth), [Fox News: exercise after baby](https://www.foxnews.com/health/exercise-after-baby-do-you-really-have-to-wait-6-weeks.amp) | Second-hand: check ACOG's own text |
| Complaints, warning complaints: 183 days | Unchanged (decided earlier) | | The doctor may want dizziness shorter (`QUESTIONS_FOR_DOCTOR.md` 2.5) |

## What we did with them

- **CKD (built 2026-11-13):** "ckd", "chronic kidney disease", "kidney
  disease" and "renal failure" in a diagnosis or complaint now send the
  patient to a doctor (`data/condition_aliases.csv`; tests in
  `backend/tests/test_safety.py`). This only makes the rules stricter.
- **Low BP (built 2026-11-13, provisional):** a BP below 90/60 in the last
  90 days leaves out floor and vigorous exercises (`data/reading_rules.csv`).
  The clinic's `BP_SYS_LOW` / `BP_DIA_LOW` flags and "hypotension" / "low BP"
  in a diagnosis or complaint show as a concern for the doctor
  (`agent/routing.py`). Not a stop on its own.
- **Underweight (built 2026-11-13, provisional):** BMI below 18.5 leaves out
  vigorous exercise, puts strength and balance first, and adds a concern;
  below 16, a doctor writes the plan (`store/plans.py` → `UNDERWEIGHT_BMI`,
  `SEVERE_THIN_BMI`; `agent/routing.py`).
- Tests for both: `backend/tests/test_low_bp_underweight.py`. Both still need
  a clinician's sign-off (`QUESTIONS_FOR_DOCTOR.md` 1b and 5.4).
