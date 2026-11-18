# Research context: VitaInspire exercise agent

Paste this into a research session. It describes the project so research can be
aimed at what we can actually use. No patient data is included.

## The product in one paragraph

VitaInspire runs clinics and medical camps in India, mostly for rural patients.
We are building a doctor-side AI agent. A doctor selects a patient; the agent
reads the patient's clinic record, works out their conditions and how severe
the case is, and either drafts a home exercise plan or, for severe cases, sends
it to the doctor to write. **A doctor approves every plan before the patient
sees it.** Patients don't chat with the agent; they only see a simple page with
their approved plan (large text, for low-end phones). The CEO wants us to go
beyond exercises: for each condition, find what else (evidence-based, safe,
practical) we could offer.

## Who the patients are

- About 41,000 adult patients (18+) in the clinic database, 76,000 visits.
- Mostly rural; 97% prefer Hindi (some Marathi), very few English. Low-end phones.
- In a random sample of 50: 38 women, 12 men; ages 20–80, median 47.
- Most common conditions in that sample: high blood pressure (about half, mostly
  controlled on medicine), knee pain, long-standing back pain, neck or back
  stiffness, diabetes (mostly controlled), overweight. Frequent complaints:
  dizziness, tingling or numbness, joint pain, weakness, acidity.
- The clinic records are short and in clinic shorthand ("HTN, T2DM",
  "OA knee", "LBA"). Many problems appear only as a complaint, not a diagnosis.

## What the agent knows about each patient (from the clinic record)

Age, sex; weight, height, BMI; vitals per visit (BP, pulse, SpO2, temperature,
blood sugar fasting/random, haemoglobin); the clinic's own flags on vitals
(HIGH, CRITICAL, ELEVATED, LOW); diagnoses (free text) and chief complaints
(free text) from the last 10 visits; medicines prescribed; a registration
questionnaire (hypertension, diabetes, thyroid, heart disease, asthma, high
cholesterol, tuberculosis, surgeries, smoking, alcohol); emergency visits and
referrals. **No lab reports, no imaging, no activity or fitness data, no diet
data.** Research that needs inputs we don't have should say so.

## How decisions are made (rules first, AI second)

1. Rules map the record to our condition codes (an alias file of clinic wording).
2. An AI reads the same record and may add conditions or raise severity, quoting
   the record. It can never remove a condition or lower severity.
3. A case is **severe** (the doctor writes the plan, no AI draft) if any of:
   a "refer" condition; BP or sugar not under control (from the clinic's flags);
   a critical vital reading; an emergency visit; a warning complaint in the last
   6 months (chest pain, breathlessness, dizziness, fainting, palpitations,
   numbness or tingling, seizure); a condition a doctor recorded as severe; or
   the AI rates it severe.
4. Otherwise the AI picks 3–5 exercises from those the safety grid allows for
   **every** condition the patient has. Doses come from fixed rules, never from
   the AI. Age 60+: one step lower dose and no running; BMI 30+: no running.
5. The doctor edits and approves. No automatic progression: any change is a new
   draft that a doctor approves again.

About 78% of patients come out severe today, so the AI drafts for roughly 1 in 5.

## The 28 conditions

**Supported** (the agent may draft exercises):

| Code | Name shown | Note |
|---|---|---|
| none | None of these | Standard program |
| chronic_back_pain | Long-standing back pain | |
| herniated_disk | Slip disc | |
| degenerative_disc | Disc wear and tear | |
| spinal_stenosis | Nerve pinching in the spine | |
| spondylosis | Neck or back stiffness | |
| arthritis_hip | Hip joint pain | |
| arthritis_knee | Knee pain | Lower impact; avoid deep knee bending under load |
| bursitis | Joint swelling | |
| carpal_tunnel | Wrist pain | |
| sprain_strain | Sprain / pulled muscle | |
| gout | Uric acid problem | |
| prediabetes | Prediabetes | |
| diabetes_controlled | Sugar under control | On medicine/diet, no known complications |
| bp_controlled | BP under control | On medicine; lower impact |
| high_cholesterol | Cholesterol problem | |
| obesity | Overweight | BMI 30+; lower impact |
| pcos | PCOD | |
| depression | Feeling low | No physical restriction |
| anxiety | Tension | No physical restriction |

**Refer** (always a doctor; no AI plan): heart_condition (heart problem),
diabetes (sugar not under control), high_bp (BP not under control), pregnancy
(pregnant or recently had a baby), recent_surgery, acute_injury (fresh injury),
neurological (nerve-related problem), other_unlisted (anything else; the
fail-closed default).

**Common problems with no condition of their own yet** (they become
other_unlisted, so a doctor decides): thyroid (hypo/hyper), shoulder pain,
multiple joint pain, foot and heel pain (plantar fasciitis), vertigo, asthma,
anaemia.

## The 12 exercises (all home, no equipment)

| Exercise | Type | Starting dose | Usual maximum | Each side |
|---|---|---|---|---|
| Walking | distance | 1 × 1 km | 1 × 5 km | |
| Running | distance | 1 × 1 km | 1 × 5 km | |
| Glute Bridge | repetitions | 2 × 5 | 3 × 15 | |
| Dead Bug | repetitions | 2 × 4 | 3 × 12 | |
| Shoulder Circles | repetitions | 2 × 5 | 3 × 15 | |
| Ankle Circles | repetitions | 2 × 5 | 2 × 15 | yes |
| Wrist Circles | repetitions | 2 × 5 | 2 × 15 | yes |
| Wall Calf Stretch | hold, seconds | 2 × 10 | 2 × 30 | yes |
| Seated Hamstring Stretch | hold, seconds | 2 × 15 | 2 × 30 | yes |
| Side-Lying Thigh Stretch | hold, seconds | 2 × 15 | 2 × 30 | yes |
| Neck Hold (isometric) | hold, seconds | 2 × 5 | 3 × 20 | |
| Seated Side Stretch | hold, seconds | 2 × 10 | 2 × 30 | yes |

**Safety grid:** a verdict for every condition × exercise: 191 safe, 46 modify
(allowed with a note), 3 avoid (Seated Hamstring Stretch for slip disc, disc
wear and spinal stenosis: loaded flexed spine). None of it is clinically
reviewed yet; a clinician must sign it off.

## What we want researched

For each condition above (supported ones first, then the gaps and the refer
ones), find what we could safely add **beyond our 12 exercises**, for example:

- Exercises or exercise types we're missing (and for which conditions), with
  starting doses and limits, doable at home without equipment.
- Other non-drug measures: breathing exercises, simple yoga-style movements,
  walking routines, posture and daily-activity advice, sleep, weight, diet
  advice suited to Indian rural diets, stress.
- Warning signs: symptoms that should stop exercise or send the patient to a doctor.
- What to avoid for each condition (contraindications), so it can go into the
  safety grid as "avoid" or "modify".
- Anything the data suggests about who benefits (by age, sex, BMI, BP, sugar).

For every recommendation, please give:

| Field | Why we need it |
|---|---|
| Condition(s) it applies to | Maps to our codes |
| The recommendation, in plain words | It may be shown to rural patients |
| Dose or frequency, and a safe upper limit | Our rules set doses, not the AI |
| Who should not do it (contraindications) | Becomes safe / modify / avoid in the grid |
| Evidence: dataset or study, and how strong | A clinician will review it |
| Which patient data would trigger it | Must use fields we actually have (listed above) |
| Fits our rules? | Home, no equipment, low risk, doctor-approved |

## Constraints on any recommendation

- Adults only. A doctor approves everything; nothing goes to a patient directly.
- Home-based, no equipment, low risk, understandable without supervision.
- Nothing for refer conditions without a doctor (heart, uncontrolled BP or sugar,
  pregnancy, recent surgery, fresh injury, nerve problems).
- No diagnosis and no medicine advice: exercise and lifestyle support only.
- Must work in Hindi and for people with low literacy (we may add pictures later).
- Prefer evidence from Indian or similar populations; say when a dataset is
  from a very different population (most Kaggle data is from the US or Europe),
  self-reported, or small.
- Check each dataset's licence before we rely on it.
