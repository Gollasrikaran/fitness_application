# Thyroid (underactive and overactive): exercise research

Researched 2026-11-18. Same layout as the other research docs: Part A is the
evidence, Part B is what we propose for the app. **Built 2026-11-18**
(sections 1–5 and 8; 390 tests pass). One change from the proposal: the
AI's own `hypothyroid` / `hyperthyroid` findings are kept as they are (they
already need a quote from the record), so `agent/assess.py` only gained the
marker's wording for the AI. All values are POC values from this research ("product-team, not
clinically reviewed"); the doctor still approves every plan. Sources at the
end, numbered [1]–[16].

## Why now

- **Third most common recorded condition** in the clinic (the colleague's
  Top 20, `Top_20_conditions.json`): Hypothyroidism 30 patients,
  Hyperthyroidism 18, after only Hypertension (372) and Diabetes (174).
- **Common in India:** about 1 adult in 10 has hypothyroidism (10.95% in 8
  cities, 5,360 adults); women 15.9% vs men 5.0%, and more with age. Another
  8% have subclinical hypothyroidism [10].
- **Our app sends every thyroid patient to a doctor today.** All five thyroid
  aliases map to `other_unlisted` (refer):

  | source | phrase | code today |
  |---|---|---|
  | long_term_condition | Hypothyroidism | other_unlisted |
  | long_term_condition | Hyperthyroidism | other_unlisted |
  | health_history | thyroid | other_unlisted |
  | text | hypothyroidism | other_unlisted |
  | text | hyperthyroidism | other_unlisted |

- **The most frequent "Not in our exercise list" item** in the temp DB's
  assessments: "thyroid" (health history) 12 times; 9 of 128 assessed
  patients mention thyroid. Wording seen: "Hypothyroidism", "Hyperthyroidism",
  "thyroid", "Hypothyroidism htn", "HT with DM with hypothyroidism with LBP",
  "Oligomenorrhea / Hypothyroidism".
- Test patients: **00d6acb5** (sent to a doctor for thyroid alone, 10 Nov),
  **0b84894f** (recorded "Hyperthyroidism", but the diagnoses say
  hypothyroidism and she takes Eltroxin: a clinic data error,
  `AI_TESTING_2026-11-05.md`).
- **What we can't see:** thyroid blood tests (TSH, T4) aren't read: the lab
  parser (`app/clinic_api.py` → `_LAB_KEYS`) knows only Hb and sugar. So we
  can't tell from data whether a thyroid problem is under control. We do have
  the **resting pulse**, the **palpitations** warning complaint, weight/BMI
  and the diagnosis wording.

## Part A: what the evidence says

### Underactive thyroid (hypothyroidism)

**What it does to the body (relevant to exercise):**
- Tiredness, weight gain, low mood, feeling cold; usually develops slowly [12].
  Treatment is a daily levothyroxine tablet, usually for life; some people
  feel better soon, others only after several months [12].
- **Muscles and joints:** muscle aches, cramps and stiffness, and joint pain
  and stiffness mainly in the hands and knees; **carpal tunnel syndrome**
  (tingling in the hand) is linked to it. Thyroid treatment is what mainly
  relieves these [14].
- **Heart and BP:** a slower heart rate and a higher **diastolic** BP, at rest
  and during exercise, both reversed by treatment (20 patients) [5]. Slightly
  worse cholesterol (LDL up, HDL down) and heart function that can show its
  limits only during exercise; reversible once thyroid levels are normal [4].
- **Exercise capacity** is reduced in subclinical hypothyroidism and improves
  after 6 months of normal TSH on treatment (23 patients) [3]; a 2025 review
  calls the evidence on overall exercise capacity weak [16].

**Does exercise help?** Two small randomised trials, both in women:
- **Ahmad 2023** [1]: 60 women aged 35–45 with hypothyroidism, **all on
  levothyroxine**. Aerobic, strength, or both combined, **low to moderate
  intensity, 3 days a week for 12 weeks**, vs no exercise. All three exercise
  groups improved thyroid hormone (T4), blood fats (lipid profile) and
  physical quality of life compared with controls. **Combined aerobic +
  strength** improved TSH and mental quality of life the most; aerobic alone
  improved fitness (estimated VO2 max) the most. No harm reported.
  Limits: small, one centre, trial registered after it ran.
- **Werneck 2018** [2]: 20 women with subclinical hypothyroidism. Supervised
  aerobic training (cycle + treadmill), 3 times a week, 60 minutes, at
  65–75% of maximum heart rate, for 16 weeks. Functional capacity,
  general health and both physical and mental quality-of-life scores
  improved by more than 10 points (the threshold for a real difference);
  controls didn't change. Thyroid symptoms didn't change. Two women were
  excluded before the start for abnormal BP and heart-rate responses on the
  exercise test. Limits: 10 per group, not blinded, treatment not reported.

**Bottom line:** for a treated underactive thyroid, the usual adult programme
(walking plus strength, low to moderate, about 3 days a week) is safe and
helps fitness, blood fats and quality of life. No source restricts any type
of exercise. The practical issues are tiredness, muscle cramps and
stiffness, and joint pain: start gently, build up slowly.

### Overactive thyroid (hyperthyroidism, thyrotoxicosis)

**What it does to the body:**
- Racing or irregular heartbeat, sweating and feeling hot, weight loss
  despite eating, shakiness [11].
- **Heart:** reduced heart and lung capacity during exercise, worse in older
  patients; can bring on **atrial fibrillation** (an irregular, fast
  heartbeat), **heart failure** and worse angina. Most heart changes return
  to normal once the thyroid is controlled [6]. The NHS lists atrial
  fibrillation, heart failure, osteoporosis and **thyroid storm** (a medical
  emergency: racing heart, high fever, confusion) as complications [13].
- **Guideline (ATA 2016)** [7]: beta-blockers are recommended for everyone
  with symptoms, **especially older patients, a resting heart rate above 90
  per minute, or heart disease** (Recommendation on beta-adrenergic
  blockade; strong recommendation, moderate-quality evidence). *The full
  text is paywalled: this wording comes from guideline summaries and must be
  checked against the original.* Beta-blockers control the racing heart and
  shakiness while thyroid levels are brought down [11].
- **Bones:** bone density is significantly lower in untreated
  hyperthyroidism and **hip fracture risk rises with age at diagnosis**;
  after treatment bone density returns to normal (meta-analysis, 20 bone
  density and 5 fracture studies) [8].
- **Muscles:** weakness of the thigh and shoulder muscles is common; a rare
  but serious form is **thyrotoxic periodic paralysis**, sudden muscle
  weakness from a low potassium level, which stops once the thyroid is
  controlled [9].
- **Timing:** thyroid levels come down over weeks to months, depending on
  the treatment [11].

**Exercise:** no trial tests exercise during untreated hyperthyroidism. The
patient-education sources agree: hold strenuous exercise until thyroid
levels are controlled, gentle walking is usually fine with the doctor's
agreement, and stop for palpitations, chest pain, fainting or severe
breathlessness [11; secondary sources in the search notes]. Once controlled,
weight-bearing exercise and balance help rebuild bone and prevent falls [8].

### Screening (ACSM)

ACSM's pre-exercise screening counts "metabolic disease" (diabetes and
**thyroid disorders that impair metabolic control**) as a reason for medical
clearance before starting exercise, for people not already active [15]. A
treated, stable thyroid problem doesn't, in itself, need clearance; an
uncontrolled one does. (Secondary source; ACSM's own text not checked.)

### Safety: what the sources agree on

| Situation | What to do | Source |
|---|---|---|
| Underactive, treated | Normal programme, start gently, build up slowly | [1][2][12] |
| Underactive, with muscle cramps, stiffness or joint pain | Lighter, slower; warm up; these usually ease with treatment | [14] |
| Underactive, with tingling in the hand | Carpal tunnel: hand exercises with care; doctor if numb or weak | [14] |
| Overactive, untreated or not yet controlled | No strenuous exercise; a doctor decides | [6][7][11][13] |
| Racing or irregular heartbeat, chest pain, fainting | Stop; see a doctor | [6][13] |
| Overactive, older patient | Higher fracture and atrial fibrillation risk; balance and fall prevention matter | [6][8] |

## Part B: what we propose for our app (to decide)

### 1. Two condition codes (`data/conditions.csv`)

| condition_code | display_name | bucket | notes (the AI and the doctor read these) |
|---|---|---|---|
| hypothyroid | Underactive thyroid | supported | Tiredness, stiff muscles and cramps are common: start gently and build up slowly, and warm up first. Some muscle ache that settles by the next day is fine. Stop and tell your doctor about a racing heartbeat, chest pain or tingling in the hands. |
| hyperthyroid | Overactive thyroid | refer | A doctor writes the plan: until it is controlled, a fast or irregular heartbeat, weak muscles and weaker bones make strenuous exercise unsafe. Once controlled: walking and light strength first; weight-bearing and balance exercises help the bones. |

Why `hyperthyroid` is "refer": we can't see thyroid blood tests, and the
risks of exercising while it is uncontrolled (atrial fibrillation, heart
failure, periodic paralysis) are the kind our rules always leave to a
doctor. Fail closed, as for `high_bp` and `diabetes`.

### 2. Aliases (`data/condition_aliases.csv`)

Replace the five `other_unlisted` rows above, and add:

| source | phrase | code |
|---|---|---|
| long_term_condition | Hypothyroidism | hypothyroid |
| long_term_condition | Hyperthyroidism | hyperthyroid |
| health_history | thyroid | thyroid_any |
| text | hypothyroidism | hypothyroid |
| text | hypothyroid | hypothyroid |
| text | hypo thyroid | hypothyroid |
| text | hypothyroidsm | hypothyroid |
| text | subclinical hypothyroidism | hypothyroid |
| text | hashimoto | hypothyroid |
| text | hashimotos thyroiditis | hypothyroid |
| text | hyperthyroidism | hyperthyroid |
| text | hyperthyroid | hyperthyroid |
| text | hyper thyroid | hyperthyroid |
| text | thyrotoxicosis | hyperthyroid |
| text | graves | hyperthyroid |
| text | graves disease | hyperthyroid |
| text | toxic goitre | hyperthyroid |
| text | toxic goiter | hyperthyroid |
| text | thyroid | thyroid_any |
| text | goitre | thyroid_any |
| text | goiter | thyroid_any |
| text | thyroiditis | thyroid_any |
| text | thyroid nodule | thyroid_any |

The longest match wins (since 2026-11-17), so "hypothyroidism" isn't also
read as bare "thyroid", and "toxic goitre" isn't read as "goitre".

### 3. "Thyroid" with the type not recorded (`thyroid_any`)

The health-history answer is just "thyroid", and many diagnoses say
"thyroid" alone. A new marker `thyroid_any`, resolved by the rules in
`agent/routing.py` like `bp_any` (proposed):

| What the record shows | Result |
|---|---|
| Any overactive wording (rules or an AI quote, e.g. a carbimazole prescription quoted by the AI) | `hyperthyroid` (doctor) |
| Latest resting pulse **90/min or above** (within its 30-day window) | `hyperthyroid` (doctor), evidence "resting pulse 96/min on …: possible overactive thyroid" (ATA's 90/min threshold [7]) |
| Neither | `hypothyroid`, named "Thyroid problem (type not recorded; treated as underactive)" so the doctor sees it was a guess |

Why default to underactive: it is far more common (1 in 10 adults in India
[10]), and the pulse check plus the existing palpitations warning complaint
catch the overactive signs we can see. Both codes found (0b84894f's data
error): the stricter one (`hyperthyroid`) wins, as for BP.

Code to change: `store/seed.py` (`ALIAS_MARKERS` + `thyroid_any`),
`agent/routing.py` (`_resolve_thyroid`, like `_resolve_asthma`),
`agent/assess.py` (`_TO_MARKER`/`_FLAGS_DECIDE`: an AI "hyperthyroid" stands
only with a quote; an AI "hypothyroid" goes through the marker), and one
line in `agent/prompts.py` → `ASSESS` ("for thyroid use hypothyroid or
hyperthyroid when the record says which; medicines can show which, e.g.
levothyroxine/Eltroxin/Thyronorm: underactive, carbimazole: overactive").
No medicine **rule**: medicines stay something the AI may quote, as for
metformin today.

### 4. Safety grid for `hypothyroid` (`data/safety_grid.csv`, 33 rows)

All "safe" except the four breath-holding exercises (diastolic BP runs
higher until treated [5]; same note as for diabetes) and Running (tiredness
and cramps). The order follows the trials: walking-type first, then
strength (combined aerobic + strength helped most [1]), balance, breathing.

| rank | activity_type | verdict | note |
|---|---|---|---|
| 1 | walk | safe | |
| 2 | march_in_place | safe | |
| 3 | sit_to_stand | safe | |
| 4 | wall_pushup | safe | |
| 5 | mini_squat | safe | |
| 6 | calf_raise | safe | |
| 7 | standing_hip_abduction | safe | |
| 8 | seated_knee_extension | safe | |
| 9 | single_leg_stand | safe | |
| 10 | heel_toe_walk | safe | |
| 11 | slow_breathing | safe | |
| 12 | wall_pelvic_tilt | safe | |
| 13 | seated_march | safe | |
| 14 | belly_breathing | safe | |
| 15 | calf_stretch | safe | |
| 16 | chair_hamstring_stretch | safe | |
| 17 | shoulder_circles | safe | |
| 18 | ankle_circles | safe | |
| 19 | glute_bridge | modify | Breathe out as you lift; don't hold your breath. |
| 20 | dead_bug | modify | Breathe out as you move; don't hold your breath. |
| 21 | lower_back_side_stretch | safe | |
| 22 | hamstring_stretch | safe | |
| 23 | quad_stretch | safe | |
| 24 | chin_tuck | safe | |
| 25 | pursed_lip_breathing | safe | |
| 26 | wrist_circles | safe | |
| 27 | neck_isometric | modify | Short holds, breathing normally; don't hold your breath. |
| 28 | wall_sit | modify | Short, shallow holds, breathing normally; don't hold your breath. |
| 29 | running | modify | Only once walking feels easy. Tiredness and muscle cramps are common until the thyroid is well treated: walk instead on those days. |
| 30 | towel_squeeze | safe | |
| 31 | fist_open | safe | |
| 32 | finger_spread | safe | |
| 33 | thumb_touch | safe | |

`hyperthyroid` is "refer": no rows needed (as for `skin_infection`).

**Example draft**, underactive thyroid alone, age under 60, normal BMI:
Walking, Sit to Stand, Wall Push-up, Standing on One Leg, Slow Breathing.
With the breath-holding ones out of the slots anyway (holding exercises are
never a slot), the four "modify" rows matter mostly when a doctor adds them.

### 5. Evidence lines (`data/exercise_benefits.csv`)

For the "why" under each exercise (plan C). Numbers only from the trial:

| condition_code | activity_type | benefit | source |
|---|---|---|---|
| hypothyroid | walk | in women with an underactive thyroid on treatment, walking-type (aerobic) training 3 days a week for 12 weeks improved fitness, blood fats and physical quality of life | research/THYROID.md (Ahmad 2023) |
| hypothyroid | march_in_place | (same as walk) | research/THYROID.md (Ahmad 2023) |
| hypothyroid | sit_to_stand | in women with an underactive thyroid on treatment, strength training 3 days a week for 12 weeks improved blood fats and physical quality of life; with walking added it helped mood-related quality of life most | research/THYROID.md (Ahmad 2023) |
| hypothyroid | wall_pushup | (same as sit_to_stand) | research/THYROID.md (Ahmad 2023) |
| hypothyroid | mini_squat | (same as sit_to_stand) | research/THYROID.md (Ahmad 2023) |
| hypothyroid | calf_raise | (same as sit_to_stand) | research/THYROID.md (Ahmad 2023) |

No lines for balance or breathing: no thyroid-specific evidence.

### 6. No new exercises, rules or windows needed

- **Exercises:** our 33 cover what the trials used (walking, body-weight
  strength). Nothing to add.
- **Reading rules:** the existing resting-pulse bands already apply
  (100–119: no vigorous; 120+: no plan). The 90/min check in section 3 is
  only for an unspecified "thyroid".
- **Warning complaints:** "palpitation(s)" is already one. Nothing to add.
- **Time windows:** none; both are long-term conditions (see question 3).
- **Later (not now):** reading TSH from uploaded lab reports (add "tsh" to
  `_LAB_KEYS`) would let the rules judge control, as for sugar. Needs the
  doctor's cut-offs (question 2).

### 7. What this does to the test patients

| Patient | Today | After |
|---|---|---|
| 00d6acb5 (thyroid alone) | Doctor: thyroid not listed | `hypothyroid` (or `thyroid_any` → underactive unless pulse 90+): an AI draft, if nothing else stops it |
| 0b84894f (recorded Hyperthyroidism, diagnoses hypothyroidism; also heart disease and BP) | Doctor | Still doctor (heart condition; and `hyperthyroid` wins over `hypothyroid`) |
| "HT with DM with hypothyroidism with LBP" patients | Doctor (thyroid) | Decided by BP, diabetes and back pain like any other patient |

### 8. Tests to add (`backend/tests/`)

- Each alias group: hypothyroid wording → `hypothyroid`; hyperthyroid
  wording → `hyperthyroid` (refer, severe); "thyroid" → `thyroid_any`.
- `thyroid_any`: pulse 96 → `hyperthyroid`; pulse 78 → `hypothyroid` with
  the "type not recorded" name; no pulse → `hypothyroid`.
- Both found → `hyperthyroid`.
- "hypothyroidism" doesn't also match bare "thyroid" (longest match).
- Grid: `hypothyroid` has a rule for all 33 exercises (the consistency test).
- A hypothyroid-only draft holds no breath-holding exercise in a slot.

## Questions for the doctor

1. Can a patient with a **treated, stable underactive thyroid** get an AI
   draft like any other patient? (Our proposal: yes.)
2. If we read **TSH** from reports later: above what TSH should a doctor
   write the plan (e.g. 10 mIU/L)?
3. **Overactive thyroid:** always a doctor, as proposed? Or, once a doctor
   records it as controlled, a separate "controlled" code like
   `bp_controlled`? Should an old diagnosis (e.g. 2 years, now treated)
   still count?
4. **"Thyroid" with no type:** is treating it as underactive, unless the
   resting pulse is 90/min or above, acceptable?
5. **Hand tingling** in a thyroid patient: we already send tingling to a
   doctor; is that right here (carpal tunnel is common with an underactive
   thyroid)?

## Sources

Primary studies and guidelines (abstracts read through PubMed E-utilities):

1. Ahmad AM, Serry ZH, Abd Elghaffar HA, Ghazi HA, El Gayar SL. Effects of aerobic, resistance, and combined training on thyroid function and quality of life in hypothyroidism. A randomized controlled trial. *Complement Ther Clin Pract.* 2023;53:101795. doi:10.1016/j.ctcp.2023.101795. [PubMed 37659172](https://pubmed.ncbi.nlm.nih.gov/37659172/)
2. Werneck FZ, Coelho EF, Almas SP, et al. Exercise training improves quality of life in women with subclinical hypothyroidism: a randomized clinical trial. *Arch Endocrinol Metab.* 2018;62(5):530–536. doi:10.20945/2359-3997000000073. [PMC10118651](https://pmc.ncbi.nlm.nih.gov/articles/PMC10118651/) (full text read)
3. Mainenti MR, Vigário PS, Teixeira PF, et al. Effect of levothyroxine replacement on exercise performance in subclinical hypothyroidism. *J Endocrinol Invest.* 2009;32(5):470–473. [PubMed 19468264](https://pubmed.ncbi.nlm.nih.gov/19468264/)
4. Kahaly GJ. Cardiovascular and atherogenic aspects of subclinical hypothyroidism. *Thyroid.* 2000;10(8):665–679. [PubMed 11014311](https://pubmed.ncbi.nlm.nih.gov/11014311/)
5. Pies M, Hellermann J, Treese N, et al. Cardiovascular parameters in transient hypothyroidism (German). *Z Kardiol.* 1995;84(9):668–674. [PubMed 8525668](https://pubmed.ncbi.nlm.nih.gov/8525668/)
6. Kahaly GJ, Nieswandt J, Mohr-Kahaly S. Cardiac risks of hyperthyroidism in the elderly. *Thyroid.* 1998;8(12):1165–1169. [PubMed 9920373](https://pubmed.ncbi.nlm.nih.gov/9920373/)
7. Ross DS, Burch HB, Cooper DS, et al. 2016 American Thyroid Association Guidelines for Diagnosis and Management of Hyperthyroidism and Other Causes of Thyrotoxicosis. *Thyroid.* 2016;26(10):1343–1421. doi:10.1089/thy.2016.0229. [PubMed 27521067](https://pubmed.ncbi.nlm.nih.gov/27521067/) (abstract only; the beta-blocker recommendation is quoted from summaries, e.g. [Consultant360](https://www.consultant360.com/exclusives/ata-updates-guidance-thyrotoxicosis-management); check against the full text)
8. Vestergaard P, Mosekilde L. Hyperthyroidism, bone mineral, and fracture risk: a meta-analysis. *Thyroid.* 2003;13(6):585–593. [PubMed 12930603](https://pubmed.ncbi.nlm.nih.gov/12930603/)
9. Lin SH. Thyrotoxic periodic paralysis. *Mayo Clin Proc.* 2005;80(1):99–105. [PubMed 15667036](https://pubmed.ncbi.nlm.nih.gov/15667036/)
10. Unnikrishnan AG, Kalra S, Sahay RK, et al. Prevalence of hypothyroidism in adults: an epidemiological study in eight cities of India. *Indian J Endocrinol Metab.* 2013;17(4):647–652. [PubMed 23961480](https://pubmed.ncbi.nlm.nih.gov/23961480/)

Patient information (for the advice wording):

11. American Thyroid Association. Hyperthyroidism (patient page). [thyroid.org/hyperthyroidism](https://www.thyroid.org/hyperthyroidism/)
12. NHS. Underactive thyroid (hypothyroidism) and its treatment. [nhs.uk](https://www.nhs.uk/conditions/underactive-thyroid-hypothyroidism/), [treatment](https://www.nhs.uk/conditions/underactive-thyroid-hypothyroidism/treatment/)
13. NHS. Overactive thyroid: complications. [nhs.uk](https://www.nhs.uk/conditions/overactive-thyroid-hyperthyroidism/complications/)
14. Mayo Clinic. Hypothyroidism: does it cause joint pain? [mayoclinic.org](https://www.mayoclinic.org/diseases-conditions/hypothyroidism/expert-answers/hypothyroidism/faq-20057789) (the page refused automated reading; content taken from search summaries of it)

Screening and reviews:

15. American Council on Exercise. New preparticipation screening guidelines (summary of ACSM 2018). [acefitness.org](https://www.acefitness.org/education-and-resources/professional/expert-articles/6921/new-preparticipation-screening-guidelines-what-health-and-fitness-pros-need-to-know/) (secondary; ACSM's own text not checked)
16. Polakowska N, Skowron P, Dyda M, et al. Influence of levothyroxine supplementation on athletic performance in subclinical hypothyroidism: a review. *Folia Med Cracov.* 2025;65(2):49–58. [PubMed 41329972](https://pubmed.ncbi.nlm.nih.gov/41329972/)

**Strength of the evidence:** the exercise trials are small (60 and 20
women) and from single centres; there is no trial in men, older adults, or
Indian patients, and none of exercise during untreated hyperthyroidism. The
bone and heart findings rest on a meta-analysis and reviews. Enough for POC
values; a clinician must review them.
