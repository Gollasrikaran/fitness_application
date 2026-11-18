# Diabetes: exercise research

Second condition for the next phase (`EXERCISE_FIT_PLAN.md`, tracker step 6),
after hypertension. Researched 2026-10-29 from published guidelines and
meta-analyses (sources at the end). Part A is what the evidence says. Part B is
what we propose for our app; it needs our decision and a clinician's review
before it becomes rules.

Scope reminder: who may exercise at all is decided by a colleague. We decide
what an eligible patient with diabetes (or prediabetes) should do, and how much.
Our codes: `diabetes_controlled` and `prediabetes` (supported), `diabetes`
(sugar not under control: refer, a doctor writes the plan).

Why diabetes next: after BP it's the most common condition in our assessments
(56 of 281: 32 not under control, 24 controlled), and the safety grid treats
controlled diabetes and prediabetes as almost entirely "safe" (16 of 17 and
17 of 17), so the grid gives the AI no guidance for them today.

## Part A: what the evidence says

### Which exercise lowers sugar, and by how much

HbA1c is the 3-month average of blood sugar; a drop of 0.5% is about what a
second diabetes tablet adds.

| Exercise type | HbA1c drop | Source |
|---|---|---|
| Aerobic (walking, cycling) | 0.5–0.7% | ACSM consensus 2022 (Kanaley) |
| Combined aerobic + strength | More than either alone (about 0.2% more than aerobic alone) | Schwingshackl 2014 (14 trials); Pan 2018 (37 trials, 2,208 patients) |
| Strength alone | Helps, ranks below aerobic and combined | Pan 2018; Garcia 2025 |
| High-intensity intervals | Ranked first in the newest network meta-analysis | Garcia 2025; mostly supervised, not for our unsupervised home setting |
| Physical-activity advice alone (no programme) | Smallest effect, but still helps | Garcia 2025 |
| Yoga (as an add-on) | Moderate (standardised effect −0.64); trials mostly from India, high risk of bias | Kumar 2016; Cui 2016 (12 trials, 864 patients) |

- **Walking after meals:** sugar rises most after meals, and moving then
  blunts the rise. In a small trial (Reynolds 2016, 41 adults), **10 minutes
  of walking after each main meal** lowered after-meal sugar about 12% more
  than one 30-minute walk at any time of day, with the same total minutes. A
  meta-analysis of 8 small crossover trials found the effect holds in type 2
  diabetes (high risk of bias). Starting soon after eating seems to work best
  (secondary sources; not checked in the original).
- **Breaking up sitting:** in a lab trial (Dempsey 2016, 24 overweight adults
  with type 2 diabetes), **3 minutes of light walking or simple strength moves
  every 30 minutes** (half-squats, calf raises, buttock squeezes, knee raises)
  lowered sugar and insulin after meals; the strength moves also lowered BP
  more. A proof of concept, not a long trial.
- **Weight:** losing visceral (belly) fat needs a fairly high volume, about
  500 kcal a session on 4–5 days a week (Kanaley 2022).

### Prediabetes: lifestyle prevents diabetes

- **Indian Diabetes Prevention Programme (IDPP-1, Ramachandran 2006):** in
  Indian adults with impaired glucose tolerance, lifestyle change (walking
  30 minutes a day, diet advice) lowered the risk of developing diabetes by
  about 28% over 3 years. Lifestyle and metformin together did no better than
  either alone. Indian, urban population: the closest evidence we have.
- RSSDI (Indian diabetes society) report on yoga: regular yoga may lower the
  risk of diabetes by up to 40% in high-risk people; the authors call for more
  trials. A prevention report, not the treatment guideline.

### What the guidelines recommend

| Guideline | Recommendation |
|---|---|
| **ADA Standards of Care** (US; section 5 every year; 2016 position statement by Colberg is the detailed version) | At least 150 min a week of moderate to vigorous aerobic activity, over at least 3 days, **no more than 2 days in a row without activity**. Resistance training 2–3 days a week on non-consecutive days. Flexibility and **balance training 2–3 times a week for older adults**. **Interrupt sitting every 30 minutes** with light activity. (The 2026 text wasn't read directly; figures from the 2016 statement and summaries.) |
| **ACSM consensus 2022** (Kanaley) | Aerobic and resistance as above; activity after meals; effort by feel: **10–12 on the 6–20 scale** (light to somewhat hard) when heart rate can't be used; reduce and break up sitting; flexibility and balance count too. |
| **WHO 2022 brief** for people with type 2 diabetes | Same targets as for everyone (150–300 min moderate a week, strength 2+ days, balance for 65+), plus less sitting. "Some activity is better than none." |
| **RSSDI 2022** (Indian, derived from the IDF guideline) | Not read in full (section on activity and yoga to check). |

### Safety: what the sources agree on

- **Low sugar (hypoglycaemia) is the main risk, and only with some medicines:**
  insulin and the sulfonylurea tablets (glimepiride, gliclazide,
  glibenclamide). The glimepiride label lists "severe or prolonged exercise"
  and missed meals among the causes. Metformin, DPP-4 tablets (sitagliptin,
  vildagliptin, teneligliptin) and SGLT2 tablets rarely cause low sugar on
  their own (general knowledge; not checked against a source here).
  - Signs: shaking, sweating, sudden hunger, a pounding heart, confusion. Low
    sugar can come **hours after** exercise, even overnight.
  - Advice in the sources: don't exercise on an empty stomach or skip a meal
    before it; carry something sweet; stop and eat it if those signs come.
    If sugar can be checked and is below about 90–100 mg/dL before exercise,
    eat 10–30 g of fast carbohydrate first (sources differ on the number).
  - **Beta-blockers** (BP medicines) can hide the shaking and pounding heart.
- **High sugar:** the 250–300 mg/dL "check ketones, don't exercise hard"
  advice comes mostly from **type 1** diabetes. For type 2, guidance says a
  person who feels well and drinks enough water may do light to moderate
  activity; vigorous effort is better left out. A severe low (below about
  50 mg/dL) or one needing help in the last 24 hours: no exercise that day.
- **Feet (peripheral neuropathy: numbness, tingling, burning):** the old advice
  to avoid walking has changed: **moderate walking doesn't increase foot
  ulcers** in people with neuropathy. But: **no weight-bearing exercise with an
  open wound or ulcer** on the foot; wear proper footwear (not barefoot, not
  loose slippers); check the feet every day for cuts, blisters and redness.
- **Eyes (advanced retinopathy):** with proliferative or severe retinopathy,
  vigorous aerobic or strength exercise is out: it can cause bleeding inside
  the eye or retinal detachment. Also avoid straining, holding the breath, and
  the head below the heart.
- **Heart (autonomic neuropathy):** a doctor clears the patient first; use
  effort by feel, not heart rate; avoid heat; drink water.
- **Heat and water:** dehydration raises sugar and makes dizziness more likely.
  SGLT2 tablets (dapagliflozin, empagliflozin) add to fluid loss. Relevant for
  outdoor walking in Indian summers: walk early morning or evening.
- **Effort by feel**, as for BP: talk test or 10–13 out of 20.

## Part B: what we propose for our app (to decide)

### 1. A weekly plan instead of a list

For an eligible patient with `diabetes_controlled` or `prediabetes`:

| Part | What | How often | How much (start → goal) | How hard |
|---|---|---|---|---|
| Aerobic, after meals | Walking (or marching on the spot indoors) **after main meals** | Daily, never 2 days off in a row | 10 min after 1 meal → after each main meal (about 150 min a week) | Can talk, not sing |
| Strength | 2–3 bodyweight exercises: sit-to-stand, wall push-up, calf raise, glute bridge | 2–3 days a week, not on consecutive days | 1–2 sets of 8–10 → 2–3 sets of 10–15 | Somewhat hard, breathing all the time |
| Sitting breaks | 3 minutes of marching, sit-to-stand or calf raises | Every 30 min of sitting, in the day | 3 min | Light |
| Balance (age 60+) | Standing on one leg holding a wall or chair; heel-to-toe walk | 2–3 days a week | 3 × 10 s each leg → 3 × 30 s | Easy, always with support |
| Stretching | Our existing stretches | After walking or strength | As today | Gentle |

Notes shown to the patient (all diabetes plans): eat before exercise, never on
an empty stomach; carry something sweet; check your feet every day; wear
footwear when walking; drink water; walk in the cooler part of the day.

### 2. Rules by sugar reading (already in `reading_rules.csv`)

Today's bands (product team, provisional) stay; the evidence supports them as
cautious for type 2:

| Latest sugar (90 days) | What we allow | Evidence |
|---|---|---|
| Below 70 mg/dL | No plan: a doctor decides | Low sugar: matches the sources |
| 70–249 | The full plan above | |
| 250–299 | No vigorous | Matches "light to moderate if feeling well" for type 2 |
| 300 or above | No plan: a doctor decides | Stricter than type 2 guidance requires; keep while unreviewed |

Questions for a clinician: should fasting and random sugar use different
bands (today they share them)? Should **HbA1c** (only from scanned lab reports,
see `PATIENT_API_FINDINGS.md`) add a band, e.g. no vigorous above 10%?

Data note: through the API only 6 of 18 diabetic patients checked had any
sugar reading, so most diabetics will have no sugar rule at all. Unlike BP,
there is no cautious default for a missing sugar reading. To decide whether we
want one (e.g. a diabetic with no reading in 90 days: no vigorous).

### 3. Rules by medicine (new; needs a medicine-name list)

The clinic record (now `/summary` → `ongoing_medicines`) lists medicine names.
Proposed:

| Medicine group | Example names (incl. common Indian brands, to check) | What we'd add |
|---|---|---|
| Insulin | insulin, Mixtard, Huminsulin, Lantus, glargine, Novomix | Low-sugar note on every plan; no vigorous; exercise 1–2 h after a meal |
| Sulfonylurea | glimepiride (Amaryl), gliclazide (Diamicron), glibenclamide | Same low-sugar note; no vigorous |
| SGLT2 | dapagliflozin, empagliflozin, canagliflozin | "Drink water" note |
| Beta-blocker | atenolol, metoprolol, bisoprolol, propranolol | Talk test, not heart rate; low-sugar signs may be hidden |
| Metformin, DPP-4 (sitagliptin, vildagliptin, teneligliptin) | | Nothing extra |

This is advice text and an intensity rule only: we never advise on the
medicine itself. Needs a clinician to check the list and the wording.

### 4. Complications: who goes to a doctor

Checked against `data/condition_aliases.csv` and `warning_complaints.csv`
(2026-10-29):

| Complication (clinic wording) | Today | Proposal |
|---|---|---|
| Neuropathy | "neuropathy" → `neurological` (refer); "numbness", "tingling" in a complaint → warning (severe). "DPN", "burning feet" have no alias | Keep refer; add the missing wordings. Later: a supported "numb feet" code with walking allowed and foot care notes |
| Foot ulcer, wound, gangrene, amputation | **No alias.** "Diabetic foot ulcer" matches only "diabetic" → `diabetes_any`, which can become `diabetes_controlled` (supported) | **Gap:** add aliases → refer. Only the AI can catch it today, and an AI `other_unlisted` becomes a concern, not a refer condition |
| Retinopathy ("DR", "PDR", "laser") | **No alias:** same gap | Add aliases → refer; if ever supported: no vigorous, no breath-holding, no head-down |
| Kidney | "Chronic Kidney Disease" (clinic condition list) → `other_unlisted` (refer). Text "CKD", "diabetic nephropathy" have no alias | Add the text wordings → refer |

The alias file belongs to the colleague's part (eligibility): raise the gaps
with them rather than change it ourselves. Candidate for `KNOWN_ISSUES.md`.

### 5. Changes to the safety grid for `diabetes_controlled` and `prediabetes`

| Exercise | Today | Proposal |
|---|---|---|
| Walking, Marching | safe | safe; rank first (after meals) |
| Sit-to-stand, Wall push-up | safe | safe; rank high (strength) |
| Running | modify (controlled), **safe (prediabetes)** | modify for both: vigorous, high impact; feet |
| Wall sit, Neck hold, Glute bridge, Dead bug | safe | modify: "breathe normally, don't hold your breath" (retinopathy may be undiagnosed) |
| Slow breathing, stretches, circles | safe | safe; rank lower (little effect on sugar) |

The ranks (`usefulness_rank`) matter: they order what the AI sees, and today
every patient gets Walking first and the same five exercises (KNOWN_ISSUES #10).

### 6. Exercises to add (candidates)

| Exercise | Type | Why |
|---|---|---|
| Calf raise (holding a wall) | Strength | Used in the sitting-break trial; standing, no floor; also helps balance |
| Standing on one leg (holding support) | Balance | Balance for older adults (ADA, WHO); we have no balance exercise |
| Heel-to-toe walk (along a wall) | Balance | Same |
| Walking after meals | Aerobic | Same exercise as Walking but timed: "10 minutes after each main meal". May be a dose format (time + timing) rather than a new exercise; decide with the weekly-plan work (tracker step 5) |

### 7. Beyond exercise (CEO's ask; advice only, no diet or medicine changes)

- Daily foot check and footwear (low cost, strong consensus).
- Break up sitting every 30 minutes.
- Sleep and stress: yoga and slow breathing as add-ons (moderate evidence,
  Indian trials).
- Diet: out of our scope; a later topic with a dietitian (Indian rural diets).

### 8. Data to check (API now works)

- How many diabetic patients have a sugar reading, and how recent.
- How the latest readings spread across the bands in point 2.
- Which diabetes medicines are most common (`ongoing_medicines`), to build the
  list in point 3.
- How often complications appear in diagnoses (timeline text).
- How many have HbA1c in scanned lab reports (later step).

## Questions for a clinician

1. Are the sugar bands right for type 2, and should fasting and random sugar
   differ? Should a missing sugar reading in a diabetic get a cautious default?
2. Should insulin and sulfonylurea patients be limited to light/moderate effort,
   and is the low-sugar advice wording right for rural patients?
3. Is moderate walking safe to recommend for patients with numb feet, given
   footwear and foot checks at home are often limited?
4. Should holds and breath-holding exercises be "modify" for all diabetics,
   since retinopathy is rarely recorded?
5. Is balance training needed for all diabetics 60+, or only with neuropathy?

## Sources

- Kanaley J. et al. Exercise/Physical Activity in Individuals with Type 2 Diabetes: A Consensus Statement from the American College of Sports Medicine. Med Sci Sports Exerc 2022;54:353–368. doi:10.1249/MSS.0000000000002800. [Summary](https://medicaldialogues.in/amp/diabetes-endocrinology/guidelines/acsm-consensus-statement-on-physical-activity-in-patients-with-type-2-diabetes-87507), [Guideline Central](https://guidelinecentral.com/guideline/1337044)
- Colberg S. et al. Physical Activity/Exercise and Diabetes: A Position Statement of the American Diabetes Association. Diabetes Care 2016;39:2065–2079. doi:10.2337/dc16-1728. [AJMC summary](https://www.ajmc.com/view/american-diabetes-association-issues-recommendations-for-physical-activity-exercise), [complications table](https://pmc.ncbi.nlm.nih.gov/articles/PMC6908414/table/T5)
- ADA Standards of Care in Diabetes 2026, section 5 (Facilitating Positive Health Behaviors and Well-being). Diabetes Care 2026;49(Suppl 1). [ACP summary](https://diabetesguide.acponline.org/archives/2025/12/12/1.htm). Not read directly.
- Pan B. et al. Exercise training modalities in patients with type 2 diabetes mellitus: a systematic review and network meta-analysis. IJBNPA 2018. [PMC6060544](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6060544/)
- Schwingshackl L. et al. Impact of different training modalities on glycaemic control and blood lipids in patients with type 2 diabetes: a systematic review and network meta-analysis. Diabetologia 2014. [Univie record](https://ucrisportal.univie.ac.at/en/publications/impact-of-different-training-modalities-on-glycaemic-control-and-/)
- Garcia et al. Network meta-analysis of exercise modalities and HbA1c, Diabetes Res Clin Pract 2025 (from a search summary; not read directly).
- Reynolds A. et al. Advice to walk after meals is more effective for lowering postprandial glycaemia in type 2 diabetes. Diabetologia 2016 (41 adults). Post-meal exercise meta-analysis: [PubMed 36715875](https://pubmed.ncbi.nlm.nih.gov/36715875/)
- Dempsey P. et al. Benefits for type 2 diabetes of interrupting prolonged sitting with brief bouts of light walking or simple resistance activities. Diabetes Care 2016. [PDF](https://acuresearchbank.acu.edu.au/download/ffe574e9e2a9eb1e52c0ae06715e339a98ea8a444fa7b5dae533d61c407e3c12/1293540/Dempsey_2016_Benefits_for_type_2_diabetes_of.pdf)
- Ramachandran A. et al. The Indian Diabetes Prevention Programme shows that lifestyle modification and metformin prevent type 2 diabetes in Asian Indian subjects with impaired glucose tolerance (IDPP-1). Diabetologia 2006;49:289–297.
- Kumar V. et al. Meta-analysis of yoga based intervention for patients with type 2 diabetes mellitus (2016). [Abstract](https://qigonginstitute.org/abstract/12384/role-of-yoga-for-patients-with-type-ii-diabetes-mellitus-a-systematic-review-and-meta-analysis); Cui J. et al. Effects of yoga in adults with type 2 diabetes: a meta-analysis. J Diabetes Investig 2016. [PMC5334310](https://pmc.ncbi.nlm.nih.gov/articles/PMC5334310)
- RSSDI Clinical Practice Recommendations for the Management of Type 2 Diabetes Mellitus 2022. Int J Diabetes Dev Ctries 2022;42(Suppl 1). [PMC9534592](https://pmc.ncbi.nlm.nih.gov/articles/PMC9534592). Activity and yoga section not read.
- WHO. Physical activity and sedentary behaviour: a brief to support people living with type 2 diabetes, 2022. [who.int](https://www.who.int/publications/i/item/9789240062740)
- Glimepiride prescribing information (low sugar after severe or prolonged exercise). [DailyMed](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=489dc098-0ac7-4f8e-b258-326229539c7c)
- Sugar before exercise, monitoring table. [PMC7510348](https://pmc.ncbi.nlm.nih.gov/articles/PMC7510348/table/T3); [CUH patient leaflet](https://cuh.nhs.uk/patient-information/pre-exercise-blood-glucose-levels)
- ADA, exercising with diabetes complications. [diabetes.org](https://diabetes.org/healthy-living/fitness/getting-started-safely/exercising-diabetes-complications)
