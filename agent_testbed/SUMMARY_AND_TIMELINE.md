# What we read from the Patient Intelligence API: summary and timeline

As of 4 November 2026.

## In short

When a doctor opens a patient, the app calls two of the Patient Intelligence
API's endpoints:

```
GET <API address>/patients/{id}/summary
GET <API address>/patients/{id}/timeline
```

- **Summary:** structured data (JSON). The patient's conditions, vitals,
  flags, medicines and the "can exercise" screening.
- **Timeline:** text, visit by visit. Complaints, diagnoses, doctors' notes and
  lab results from uploaded reports.

Our code combines the two into one patient record. The safety rules, the AI
and the doctor's screen all work from that record. Both answers are kept for
5 minutes, so opening the same patient again doesn't call the API again.

These are read-only requests. We never call the API's paid AI review.

## 1. Summary

### What we use

| Field | What it holds | What we use it for |
|---|---|---|
| `age_years`, `sex` | Age and sex | Patients under 18 are left out; age 60+ lowers doses and removes floor and high-impact exercises |
| `long_term_conditions` | Conditions a doctor recorded (e.g. Hypertension, Diabetes Mellitus) | Condition codes for the safety rules |
| `health_history` | The registration questionnaire (asthma, BP, diabetes, smoking…) | Condition codes; other history shown to the doctor |
| `visits` | The last 10 visits: date, doctor, emergency, referral | Doctor names, emergency and referral alerts |
| `vitals` | Readings per visit, with dates: BP, pulse, SpO₂, temperature, weight, height, sugar, Hb | The safety rules (latest reading within 90 days), BMI, the screen, the AI |
| `vital_flags` | The clinic's own marks on readings, e.g. `BP_SYS_HIGH`, `CRITICAL` | Deciding whether BP, diabetes or asthma is under control (last 5 visits); a critical flag sends the plan to a doctor |
| `ongoing_medicines` | Not used since 2026-11-16 | It lists every medicine ever prescribed, not the current ones (bd8b445c: 28 listed, 7 on the latest prescription). Current medicines now come from the timeline (section 2) |
| `exercise_suitable`, `patient_type` | The API's "can this patient exercise?" check and main type | A warning line on the draft when "not suitable". It never blocks the draft; the doctor decides |
| `clinical_snapshot` → `flags` | Clinical flags, e.g. "Critical lab values", "Persistent bleeding" | High and medium flags are shown to the doctor and the AI |
| `clinical_snapshot` → `encounters`, `span` | Number of visits, first and last visit date | The visit count on the screen |

An example of the `vitals` field:

```json
"vitals": [
  { "visit_id": "858ac302-…", "visit_date": "2026-06-06",
    "readings": [
      { "label": "Pulse", "value": "86 bpm", "date": "2026-06-06" },
      { "label": "SpO₂",  "value": "96%",    "date": "2026-06-06" },
      { "label": "Weight", "value": "70 kg", "date": "2026-06-06" }
    ] }
]
```

### What we don't use

| Field | Why |
|---|---|
| `patient_type_reason`, `exercise_reason`, `types` | The reasons behind the screening; we show only its result |
| `ai_review` | The API's own AI review; never requested (it costs money) |
| `clinical_snapshot` → `active`, `active_meds`, `timeline`, `dates` | Covered by other fields |

## 2. Timeline

The timeline is text, one block per visit. An example (shortened):

```
DATE: 2026-06-06
  VISIT ID: 858ac302-…
  Chief Complaint (database): Report check, 6 month heavy bleeding, abdominal pain
  Provisional Diagnosis (database): Not Documented
  Confirmed Diagnosis (database): Not Documented
  Prescription Instructions (database): DUB
Perimenopause ; Heavy bleeding
Lmp ??
  Vitals (database): Pulse: 86 bpm, SpO₂: 96%, Weight: 70 kg
  Medicines — Prescription (database):
    • Tab shelcal-XT, dosage 0-1-0, …
  Supporting Document(s): 6 found
    Lab Results (Document 2):
      • Haemoglobin: 6.5 g/dL (Ref: 12 - 17.5 g/dL) [Critical (Low)]
```

### What we read, per visit

| Line | What we use it for |
|---|---|
| `DATE`, `VISIT ID` | Putting visits in order (newest first) and matching them to the summary's vitals |
| `Chief Complaint` | Warning signs (chest pain, breathlessness, dizziness…) and condition words, from the last 6 months; the screen and the AI |
| `Provisional Diagnosis`, `Confirmed Diagnosis` | Condition codes (e.g. "Htn" → BP, "bronchial asthma" → asthma); the screen and the AI. "Not Documented" counts as empty |
| `Prescription Instructions` (the doctor's notes) | The screen (latest 3 notes, plus every visit in Visit history) and the AI. Kept whole when they run over several lines. **Not** used by the rules, because notes can also say things like "no DM" |
| `Lab Results` lines | Each test with its value and status (Normal, High, Critical (Low), Unverified). Shown to the doctor and the AI. A report uploaded twice is counted once |
| `Medicines — Prescription` | Each visit's medicines (name, dosage, frequency, duration), shown in Visit history. "Current medicines" is the latest day with a prescription; two visits on that day are merged. Shown to the doctor and the AI only; we don't build rules on medicines (since 2026-11-16) |

**Lab results used by the safety rules:**
- Only **haemoglobin** (g/dL) and **blood sugar** (mg/dL).
- They count for **6 months** (vitals count for 90 days).
- If a test was done twice at one visit, the worse value counts: the lowest Hb, the highest sugar.
- "Unverified" results (possibly misread from a scan) and results in other units, such as mmol/L, are shown but never used by the rules.

### What we skip

| Line | Why |
|---|---|
| `Vitals (database)` | We take vitals from the summary, where each reading is separate and dated |
| `Age/Sex (document)`, document headers, visit counts | Age and sex come from the summary |

## 3. Why the timeline matters most

Our safety rules work on **condition codes**: names like `bp_controlled`,
`arthritis_knee` or `asthma_controlled`, which pick the patient's rows in our
safety grid (`data/safety_grid.csv`). Condition codes come from **both**
endpoints, but the timeline is where most of them come from.

**How a code is found:** our file `data/condition_aliases.csv` lists 144
words and phrases, each pointing to a code. The rules look for them in the
patient's record:

| Where the rules look | Endpoint | Phrases in our file | Example |
|---|---|---|---|
| Diagnoses and complaints, per visit | **Timeline** | **116** | "OA knee" → `arthritis_knee`, "Htn" → BP |
| Conditions a doctor recorded | Summary | 21 | "Hypertension" → BP |
| Health-history questionnaire | Summary | 7 | "asthma" → asthma |

**What only the timeline can give us:**
- **19 of our codes can only be found in diagnoses and complaints.** They are
  not on the recorded-condition list or the questionnaire at all:
  - knee, hip and back problems: arthritis, spondylosis, slipped disc,
    spinal stenosis, degenerative disc, bursitis
  - injuries, sprains and recent surgery
  - carpal tunnel and gout
  - pregnancy and PCOS
  - "uncontrolled" BP or diabetes (when a doctor writes it) and prediabetes
  - obesity (also found from BMI)
- **Every warning sign** (chest pain, breathlessness, dizziness, fainting,
  tingling…) comes from timeline complaints. In our 28-patient test, 11
  patients went to the doctor because of one.
- **Diagnoses we don't cover yet** (e.g. plantar fasciitis) are spotted in the
  timeline, so the patient goes to a doctor instead of getting a plan that
  ignores them.

**What the summary adds:**
- The long-term conditions a doctor recorded and the questionnaire answers.
  These cover BP, diabetes, asthma, COPD, heart and nerve problems,
  cholesterol, anxiety and depression.
- The clinic's **vital flags**, which decide whether BP, diabetes or asthma is
  under control.
- Weight and height, for BMI (obesity at 30 or above).

**So:** without the summary we would miss recorded long-term conditions and
whether they are under control. Without the timeline we would miss most joint,
back and injury conditions and every warning sign. Both are needed, and the
timeline does most of the work.

The doctors' notes in the timeline are the one part the rules don't read
(see section 2). A condition written only in a note, like "DM not taking any
treatment", is not turned into a code. The doctor sees it on screen.

## 4. How the two are combined

1. Visits come from the timeline, sorted **newest first**. Some patients'
   timelines list the oldest visit first, so we always sort.
2. Each visit gets its vitals from the summary, matched by visit ID, and its
   lab results from the timeline. A reading taken at the visit wins over the
   same value from a lab report.
3. Each visit gets its doctor from the summary. The summary covers only the
   last 10 visits, so older visits have no doctor name.

## 5. How much of it is used where

We fetch everything. The limits below decide what each part of the app uses.

| Who | Uses |
|---|---|
| **The doctor's screen** | Everything, including every visit in the Visit history picker |
| **The AI** (chat and assessment) | The last 10 visits, with their readings, lab results and notes |
| **The safety rules** | Vitals from the last 90 days, lab results from the last 6 months (the doctor can include older readings, only to make a plan stricter), complaints from the last 6 months, vital flags from the last 5 visits, recorded conditions and health history with no time limit |

## 6. In production

With `CLINIC_SOURCE=db`, neither endpoint is used. The same patient record is
built straight from the clinic database, read-only. Two differences:
- the database version doesn't read lab results from uploaded reports (Hb or
  sugar recorded with a visit's vitals is still used)
- it has no "can exercise" screening

Everything else is the same.
