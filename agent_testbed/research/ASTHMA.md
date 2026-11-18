# Asthma: exercise research

Third condition for the next phase (`EXERCISE_FIT_PLAN.md`, tracker step 6),
after hypertension and diabetes. Researched 2026-10-30 from published
guidelines, reviews and trials (sources at the end), and checked against our
own patients. Part A is what the evidence says. Part B is what we propose for
our app; it needs our decision and a clinician's review before it becomes
rules. Reviewed once (2026-10-30) and corrected.

Scope reminder: a colleague has already sorted which patients can exercise
(`exercise_suitable` in the Patient Intelligence API); that work is done. We
decide what a patient with asthma should do, how much, and what to watch for.

## Where asthma stands in our app today (2026-10-30)

- **No condition code.** `data/condition_aliases.csv` maps `Asthma`, `COPD`
  (clinic condition list), `asthma` (health history) and the text `asthma`,
  `copd` to `other_unlisted`, a refer condition. So every asthma patient is
  severe and a doctor writes the plan; no exercise rule ever applies.
- **Breathlessness is a warning complaint** (`breathlessness`, `shortness of
  breath`, `dyspnoea`… in `warning_complaints.csv`): one in a complaint in the
  last 6 months makes the case severe. "Wheezing" is not in the list.
- **SpO2 bands already exist** (`reading_rules.csv`): below 94% no vigorous,
  below 92% no plan. The only reading we have that matters for asthma.
- **Exercise library:** our 25 exercises have one breathing exercise (Slow
  Breathing). No asthma grid rows.
- **Already in the code, and relevant:** at age 60+ or BMI 30+, `candidates()`
  leaves out high-impact and floor exercises (so Running never reaches an older
  patient's draft). An exercise is allowed only if the grid allows it for
  **every** condition the patient has; "avoid" for any one removes it, and the
  "modify" notes of all conditions are shown together. So the strictest
  verdict already wins when asthma comes with BP or diabetes.

Two data sources are used below. The **temp DB** holds the assessments our
app has already run (94 patients, from when the clinic DB was readable). The
**Patient Intelligence API** is how we read patients now that the clinic DB is
suspended; it was used to find asthma patients (400 checked).

## Part A: what the evidence says

### Does exercise help, and is it safe?

| Evidence | What was found | How sure |
|---|---|---|
| **Physical training**, Cochrane (Carson 2013): 21 trials, 772 people | Fitness clearly better (VO2max +4.9 mL/kg/min). Quality of life better in 4 of 5 studies. No change in lung function. **No trial reported asthma getting worse.** | Moderate |
| **Aerobic training**, meta-analysis (Hansen 2020, ERJ): 11 trials, 543 adults, mean age 36, mean BMI 27.6 | Better asthma control (SMD −0.48); small gain in lung function; no change in airway inflammation. Programmes: walking, jogging, cycling, treadmill; at least 2 a week for 8–12 weeks | Moderate |
| **Aerobic exercise**, systematic review (Ang 2023, J Asthma): 10 trials + 4 studies | Asthma control and quality of life better in all but 3; no serious adverse events | Low to moderate |
| **Breathing exercises**, Cochrane (Santino 2020): 22 trials, 2,880 adults with mild to moderate asthma (14 yoga, 4 breathing retraining, Buteyko, Papworth, diaphragmatic) | Quality of life better at 3 months; fewer over-breathing (hyperventilation) symptoms at 4–6 months; FEV1 % predicted +6.9%. **Day-to-day asthma symptoms probably not changed.** Harms not studied | Moderate |
| **Yoga**, Cochrane (Yang 2016): 15 trials, 1,048 people, **mostly from India** | Small gains in quality of life and symptoms; may reduce medicine use; no clear change in lung function | Low (flawed trials) |
| **Weight loss + exercise in obese asthma** (Freitas 2017, AJRCCM): 55 adults | Adding aerobic + strength training to a weight-loss programme improved asthma control (ACQ −0.7 vs −0.3), weight loss (−6.8% vs −3.1%), fitness and quality of life, compared with breathing and stretching only | Moderate (one small trial) |

In short: regular moderate exercise is safe in controlled asthma, improves
fitness and asthma control, and is endorsed by the guidelines. Breathing
exercises add quality of life but don't replace medicine.

**Our patients are not the trial patients.** The trials studied younger, often
overweight adults (Hansen: mean age 36, BMI 27.6). Our asthma patients are
mostly 61–78, often with high BP, and some underweight (BMI 15–17). In India an
older, underweight, breathless patient labelled "asthma" may have COPD from
cooking smoke, or lung damage after tuberculosis. The evidence above applies to
them only loosely: a reason to keep the plan gentle and to send unclear cases
to a doctor.

### What the guidelines recommend

| Guideline | Recommendation |
|---|---|
| **GINA** (Global Initiative for Asthma; the main asthma guideline) | Regular physical activity for all people with asthma; no doses given. Weight loss for obese patients. Since 2019 the preferred reliever is low-dose **budesonide-formoterol** (in India: Foracort) taken as needed, which can also be taken before exercise; salbutamol-only treatment (no controller) is not recommended. (From GINA-derived summaries; the report itself not read.) |
| **EAACI position paper 2025** (European Academy of Allergy and Clinical Immunology; first exercise prescription for asthma) | **Aerobic:** 3–5 days a week, 30–40 min, moderate (can talk but not sing; effort 12–13 out of 20), vigorous or intervals only if tolerated. **Strength:** 2–3 days a week, 2–4 sets of 8–12, bodyweight for beginners; at least twice a week in severe asthma and on long-term steroids (muscle and bone). **Stretching:** 2–3 days a week or daily, holds of 10–30 s, 2–4 times. **Warm-up and cool-down:** 5–10 min each. Read in full. |
| **ATS 2013** (American Thoracic Society) on exercise-induced asthma | Reliever (salbutamol) about 15 min before exercise; warm-up with short bursts (intervals) before planned exercise; nose breathing or a scarf in cold air; avoid polluted air. Older than GINA's change to budesonide-formoterol. The burst warm-up was studied mostly in young, fit people. |
| **ICS/NCCP 2015** (Indian Chest Society and National College of Chest Physicians, Lung India) | Lists biomass smoke, tobacco smoke, infections, occupation, exercise, aspirin and beta-blockers as triggers. Exercise-induced symptoms are prevented by regular inhaled steroid or montelukast. Exercise section not read in full. |
| **WHO 2020** (everyone) | 150–300 min moderate activity a week; strength 2+ days; balance for 65+. Applies to people with asthma too. |

### Exercise-induced asthma

- Most people with asthma get symptoms during or just after exercise
  (cough, wheeze, chest tightness), worst 5–15 min after stopping.
- Triggered by breathing large amounts of **cold, dry air**; worse in dust,
  smoke and pollution.
- Prevention: a warm-up; the reliever before exercise if the doctor has said
  so; breathing through the nose; a scarf over the nose and mouth in cold air;
  steady effort rather than sudden hard effort.
- Persistent symptoms with exercise mean the asthma isn't controlled: a doctor
  should review the treatment (GINA), not the exercise plan.

### Breathing techniques

| Technique | How | Evidence |
|---|---|---|
| Diaphragmatic (belly) breathing | Sit; one hand on the chest, one on the belly; breathe in through the nose so the belly rises, the chest stays still; breathe out slowly | In the Cochrane breathing review; small trials favour it |
| Pursed-lip breathing | Breathe in through the nose for 2 counts; breathe out through pursed lips (as if blowing out a candle) for 4 counts, twice as long as in | Mostly studied in COPD; small asthma trials; helps when breathless |
| Nose breathing, slow breathing (Buteyko, Papworth, pranayama) | Slower, gentler breathing through the nose; relaxation | In the Cochrane review; pranayama is the Indian form of the yoga trials |
| Inspiratory muscle training | A device, 30 breaths twice a day | EAACI: optional for motivated patients; needs a device, not for us |

Practise when well, not during an attack. Breathing exercises never replace
the inhaler.

### Safety: what the sources agree on

- **Carry the inhaler the doctor prescribed for breathlessness**, and stop if
  symptoms persist. (For many of our patients this is Foracort, not a blue
  salbutamol inhaler: see GINA above.)
- **No exercise during an attack or after a recent one** until symptoms and
  breathing have recovered (EAACI). No source gives a reading cut-off.
- **Peak flow** below 80% of the person's best is the "yellow zone" in asthma
  action plans (NHLBI). **We have no peak flow or spirometry in the clinic
  record**, so this can't be a rule.
- **Air and weather:** move indoors, or switch to low-breathing exercise
  (strength, balance, stretching) on smoky, dusty, very cold or very hot days.
  India's official National AQI (CPCB) says the **"Moderate" band (101–200)**
  may cause breathing discomfort to people with lung disease and asthma
  (wording as quoted by several sources; CPCB's own table not read). In India:
  crop-burning season, cooking smoke (chulha), dusty roads, cold winter
  mornings.
- **Very high training volumes** (10–15+ hours a week of hard exercise) can
  harm the airways: irrelevant for our patients.
- **Effort by feel:** talk test or 12–13 out of 20. Heart-rate targets are
  unreliable (asthma and BP medicines change the pulse).

### Asthma or COPD?

- Asthma: about 2–3.5% of people in India. COPD: about 7% of adults 30+, mostly
  from biomass cooking smoke (over 60% of homes) and tobacco; often
  misdiagnosed as asthma in older patients, and spirometry is rarely available.
- COPD is a different disease: fixed narrowing, often older, often heart
  disease too. Its exercise programme is **pulmonary rehabilitation**. A
  "no cost" home programme from India (Gothi 2018, randomised: walking, stair
  climbing, sit-to-stand, wall push-ups, 30 min twice a day) helped.
- Our clinic text mixes them ("COPD", "COAD", "bronchial asthma", "LRTI").
  Proposal: treat COPD separately and keep it refer for now.

### Open source (GitHub)

Searched 2026-10-30. Nothing encodes exercise rules for asthma. Found:
ResearchKit AsthmaHealth (archived study app: inhaler use, peak flow),
air-quality alert apps, and risk-prediction models. The guidelines above are
the only source for rules.

## Part B: what we propose for our app (to decide)

### 1. A weekly plan instead of a list

For an adult patient with controlled asthma:

| Part | What | How often | How much (start → goal) | How hard |
|---|---|---|---|---|
| Warm-up | Marching on the spot, building up slowly; 3–4 short faster bursts only for patients under 60 without high BP | Every session | 5 → 10 min | Light |
| Aerobic | Walking (or marching indoors on bad-air days) | 3–5 days a week | 10–15 min → 30 min | Can talk, not sing |
| Strength | 2–3 bodyweight exercises: sit-to-stand, wall push-up, calf raise, glute bridge | 2–3 days a week | 1–2 sets of 8 → 2–3 sets of 10–12 | Somewhat hard, breathing out on effort |
| Breathing | Belly breathing, pursed-lip breathing, slow breathing | Daily, when well | 5 → 10 min | Relaxed |
| Cool-down and stretching | Slow walking, then our stretches | After every session | 5–10 min | Gentle |

For our older, often underweight patients the weight is on chair and standing
strength, easy walking and breathing.

Notes shown to the patient (all asthma plans): always warm up; stop and rest
if you cough, wheeze or feel tight in the chest, and see your doctor if it
doesn't settle; walk away from smoke, dust and traffic; exercise indoors on
smoky, very cold or very hot days; don't exercise during a bad spell of asthma.

### 2. Rules by reading

- **SpO2:** today's bands stay (below 94% no vigorous; below 92% no plan).
  For asthma, below 94% also counts as "not controlled" (point 4).
- **Pulse:** today's bands stay (resting pulse 100–119 no vigorous; 120+ no
  plan).
- **No peak flow, no spirometry:** no reading tells us whether asthma is
  controlled. Control comes from the record (point 4).

### 3. Medicines (research notes only; not built)

We don't build medicine rules into the app. Kept here as findings for the
clinician and the doctor's view.

| Medicine | Example names (Indian brands, to check) | What it tells a reader |
|---|---|---|
| Reliever | salbutamol (Asthalin), levosalbutamol (Levolin) | Asthma present. Salbutamol alone with no controller is a control concern (GINA) |
| Controller inhaler | budesonide (Budecort), budesonide + formoterol (Foracort), fluticasone + salmeterol (Seroflo), beclomethasone | Asthma treated. Foracort may be the reliever too (GINA) |
| Duolin (levosalbutamol + ipratropium) | Inhaler vs respules | The inhaler is maintenance; only **respules / nebulisation** suggest a recent attack |
| Tablets | montelukast (Montair, Montek LC), theophylline / doxofylline (Deriphyllin) | **Don't confirm asthma alone:** montelukast is also for allergy, theophylline for cough. Theophylline raises the pulse and has a narrow safety margin (palpitations) |
| Steroid tablets | prednisolone (Omnacortil, Wysolone), deflazacort | A recent bad spell **only when asthma is already present** (also used for skin, joints, allergy) |
| Non-selective beta-blockers | propranolol, carvedilol, labetalol; **timolol eye drops** (glaucoma, common at 60+) | Can set off asthma |

### 4. Condition codes

Today every asthma patient is refer. Proposal:

| Code | Bucket | When |
|---|---|---|
| `asthma_controlled` (new) | supported | Asthma in the record (health history, condition list or diagnosis text), and none of the "not controlled" signs |
| `asthma_uncontrolled` (new) | refer | Asthma with any of: breathlessness or wheeze in a complaint in the **last 6 months**; an emergency visit; latest SpO2 below 94%; the colleague's flags "Recurring respiratory symptoms" or "Asthma / COPD not settling" |
| `copd` (new) | refer | COPD, COAD, chronic bronchitis, emphysema. A separate programme (pulmonary rehab) later |

- **One window:** 6 months, the same as the warning-complaint rule. For
  breathlessness the warning rule already makes the case severe; the asthma
  rule adds wheeze, SpO2 and the colleague's flags.
- **No medicine signals** (point 3): control comes from complaints, visits,
  readings and flags.
- **Adults only:** the API's doctor lists include children (a 4-year-old in our
  sample): we keep our 18+ filter.
- Aliases to add: `bronchial asthma`, `br asthma`, `BA`, `hyperreactive
  airway`, `allergic bronchitis` → asthma (a marker `asthma_any`, decided like
  `bp_any`); `COAD`, `chronic bronchitis`, `emphysema` → `copd`. "Wheeze /
  wheezing" as a warning complaint.

### 5. Safety grid for `asthma_controlled`

| Exercise | Verdict | Note |
|---|---|---|
| Walking, Marching on the Spot, Seated Marching | safe; rank first | |
| Sit to Stand, Wall Push-up, Calf Raise, Side Leg Raise, Seated Knee Straightening | safe; rank high | Strength; low breathing demand |
| Slow Breathing; Belly Breathing and Pursed-lip Breathing once added (point 6) | safe; rank high | Daily |
| Glute Bridge, Dead Bug, Wall Sit, Neck Hold | safe | No asthma-specific reason to limit holds |
| Stretches, circles, balance, Chin Tuck | safe | |
| Running | modify | "Warm up first; not in cold, smoky or dusty air." Never reaches patients 60+ or BMI 30+ (already left out as high impact) |

With BP or diabetes, the strictest verdict of all the patient's conditions
wins and all notes are shown (already how the code works).

### 6. Exercises to add

| Exercise | Type | Dose | Why |
|---|---|---|---|
| Belly Breathing (diaphragmatic) | breathing | 1 × 5 min, up to 10 | Cochrane breathing review; seated; no risk |
| Pursed-lip Breathing | breathing | 1 × 5 min, up to 10 | Helps when breathless; also for COPD later |

Both `time` in minutes, chair, light, low impact, like Slow Breathing. Each
needs a grid row for every condition.

## Our patients (Patient Intelligence API, 2026-10-30)

400 adults and children from the busiest doctors' lists (2+ completed visits),
read through `/summary` and `/timeline`. Only counts are written here, no
patient IDs.

**17 flagged, 13 real (3.3%):** 12 with asthma in the health history, 1 COPD.
Not asthma: theophylline for a cough, a fluticasone nose spray, Montek LC
(allergy), and a 4-year-old on a nebuliser.

**Who would get an asthma plan**, counted step by step (a patient can have
several reasons, so each step only removes those still left):

| Step | Left |
|---|---|
| Asthma or COPD | 13 |
| Remove COPD | 12 |
| Remove breathlessness in a complaint | 6 |
| Remove steroid tablets ongoing (a recent bad spell; noted for the count, not a rule) | 4 |
| Remove "not suitable" (colleague) | **2** |

Of the 2: one has SpO2 96% and pulse 81; the other SpO2 95% (93–94% at
earlier visits) and pulse 103–105, so vigorous is already left out. **An asthma
code changes little in numbers today; its value is getting the rules right for
these few and for future patients.**

How asthma is recorded (13 real):
- **Health history `asthma: present`: 12. The main signal.** Notes rarely filled.
- **Diagnosis text:** mostly "bronchial asthma" / "Htn bronchial asthma"; "Copd"
  once. Our text alias `asthma` already matches "bronchial asthma".
- **Long-term conditions:** `Asthma` for 1.

Who they are (13 real): 8 women, 5 men; 10 aged 57–78, two aged 29 and 30.
High BP in 7, diabetes in 2. **Three underweight (BMI 15–17):** frailty, not
weight loss, is the concern.

Readings (13 real):
- SpO2 recorded for all. One patient at 92% at three visits (and breathless);
  one at 93–94%. The rest 95–99%.
- Resting pulse above 100 in 4.

Control:
- **Breathlessness or breathing difficulty in a complaint: 6 of 13.** Severe
  today under the warning rule.
- The colleague's flags: "Recurring respiratory symptoms" (7) and "Asthma /
  COPD not settling" (3) mostly fall on the same breathless patients.
- `exercise_suitable` is true for 9 of 13, including breathless patients and
  the one at SpO2 92%. Our own rules (warning complaints, SpO2 bands, the
  asthma code) are what keep them from an exercise draft.

Medicines seen (notes only): Foracort most common; theophylline / Deriphyllin
common; Duolin inhaler in 2; Seroflo 1; Asthalin 1; prednisolone / Omnacortil 2.

## Questions for a clinician

1. Is the controlled / not-controlled split in point 4 right, and are the signs
   (6 months; wheeze; SpO2 below 94%; the respiratory flags) the right ones
   without peak flow?
2. Should "wheeze / wheezing" be a warning complaint like breathlessness?
3. Is SpO2 below 94% the right line for asthma?
4. How do we handle "COPD" written for older patients exposed to cooking
   smoke, and possible lung damage after tuberculosis: refer for now, a
   pulmonary rehab programme later?
5. Should the warm-up include short bursts at all for patients 60+ or with
   high BP?
6. In our clinic, is Foracort used as the reliever? (Affects the wording of
   the "carry your inhaler" advice the doctor gives.)

## Sources

- Carson K. et al. Physical training for asthma. Cochrane Database Syst Rev 2013;(9):CD001116. [Cochrane Library](https://cochranelibrary.com/cdsr/doi/10.1002/14651858.CD001116.pub4/information)
- Santino T. et al. Breathing exercises for adults with asthma. Cochrane Database Syst Rev 2020;(3):CD001277. [Cochrane summary](https://www.cochrane.org/evidence/CD001277), [PubMed 32212422](https://pubmed.ncbi.nlm.nih.gov/32212422/)
- Yang Z. et al. Yoga for asthma. Cochrane Database Syst Rev 2016;(4):CD010346. [Cochrane Library](https://cochranelibrary.com/cdsr/doi/10.1002/14651858.CD010346.pub2)
- Hansen E. et al. Effect of aerobic exercise training on asthma in adults: a systematic review and meta-analysis. Eur Respir J 2020;56:2000146. [PubMed 32350100](https://pubmed.ncbi.nlm.nih.gov/32350100/)
- Ang et al. Effects of aerobic exercise on asthma control and quality of life in adults: a systematic review. J Asthma 2023. [PubMed 35862617](https://pubmed.ncbi.nlm.nih.gov/35862617/)
- Exercise Recommendations and Practical Considerations for Asthma Management: an EAACI Position Paper. Allergy 2025;80(6):1572–1591. [PMC12186601](https://pmc.ncbi.nlm.nih.gov/articles/PMC12186601/) (read in full)
- Parsons J. et al. An Official American Thoracic Society Clinical Practice Guideline: Exercise-induced Bronchoconstriction. Am J Respir Crit Care Med 2013;187:1016–27. [Guideline Central summary](https://guidelinecentral.com/guideline/7200), [ATS PDF](https://THORACIC.ORG/statements/resources/allergy-asthma/exercise-induced-bronchoconstriction.pdf)
- GINA and budesonide-formoterol before exercise: [GINA 2023 in a nutshell](https://practicenurse.co.uk/guidelines/gina-2023-guideline-in-a-nutshell), [Australian Asthma Handbook: exercise](https://www.asthmahandbook.org.au/clinical-issues/exercise), [US Pharmacist 2023](https://www.qgdigitalpublishing.com/article/Managing+Exercise-Induced+Bronchoconstriction/4603403/795563/article.html). GINA's endorsement of exercise without doses: [Hull repository paper](https://hull-repository.worktribe.com/OutputFile/5172774). GINA report not read directly.
- Agarwal R. et al. Guidelines for diagnosis and management of bronchial asthma: Joint ICS/NCCP (I) recommendations. Lung India 2015;32(Suppl 1):S3–S42. [PMC4405919](https://pmc.ncbi.nlm.nih.gov/articles/PMC4405919). Exercise section not read.
- Freitas P. et al. The role of exercise in a weight-loss program on clinical control in obese adults with asthma. Am J Respir Crit Care Med 2017. [Springer summary](https://www.springermedizin.de/the-effects-of-exercise-training-in-a-weight-loss-lifestyle-inte/9751928)
- Beta-blockers in asthma: [PMC8689715](https://pmc.ncbi.nlm.nih.gov/articles/PMC8689715), [GPnotebook](https://gpnotebook.com/pages/respiratory-and-chest-medicine/beta-blockers-and-asthma)
- Asthma action plan zones: [AAAAI action plan](https://www.aaaai.org/Aaaai/media/Media-Library-PDFs/Conditions%20Treatments/Asthma/Asthma-Action-Plan.pdf)
- Breathing technique instructions: [American Lung Association](https://lung.org/lung-health-diseases/wellness/breathing-exercises), [UCLA Health](https://uclahealth.org/news/how-use-breathing-exercises-improve-asthma)
- National AQI health statements (CPCB, as quoted): [GKToday](https://www.gktoday.in/gk/national-air-quality-index/), [APSED](https://www.apsed.in/post/what-is-aqi-india-air-quality-index-explained), [CPCB AQI report (NIUA copy)](https://smartnet.niua.org/sites/default/files/resources/Air%20Quality%20Index.pdf)
- Asthma and COPD in India: [PMC4880576](https://pmc.ncbi.nlm.nih.gov/articles/PMC4880576), [IndiaSpend](https://indiaspend.com/this-disease-is-the-2nd-highest-killer-of-indians-yet-doctors-or-patients-do-not-know-enough-about-it)
- Home-based pulmonary rehabilitation in India (incl. Gothi 2018): [PMC12053948](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12053948/)
- Indian inhaler brands (pharmacy listings, to check with a pharmacist): [Apollo Pharmacy](https://www.apollopharmacy.in/medicine-substitute/foracort-200-rotacap)
- GitHub: [ResearchKit/AsthmaHealth](https://www.github.com/ResearchKit/AsthmaHealth)
