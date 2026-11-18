# Patient Intelligence API: what we tested

Results of calling every endpoint of the Patient Intelligence API (Anushka's)
on 2026-10-29. The plan before testing, with the field lists from her
`USAGE.md`, is in `API_COVERAGE.md`; this file is what the live API actually
returns. Only structure was printed (field names, labels, value formats with
digits masked), never patient values.

## Update 2026-10-29 (afternoon): after Anushka's fix

Rechecked on 61 patients (18 diabetic). Most of "What's missing" below is now
fixed; the rest of this file is the first test, kept for the record.

| Was missing | Now |
|---|---|
| Sugar | ✅ `/summary` → `vitals` and the timeline: labels `Fasting Sugar`, `Non-fasting Sugar`, `Sugar`, as `"123 mg/dL"`. Rare: 7 of 61 patients (6 of 18 diabetics) have one |
| Hb | ✅ Included (Anushka). Rare: none in the 61 checked, so the exact label is still to see |
| The clinic's vital flags | ✅ New `/summary` → `vital_flags`: `{visit_id, date, metric, code, severity, value}`, e.g. `BP_DIA_ELEVATED` / `ABNORMAL`. Covers **all visits**: we take the last 5 ourselves |
| Emergency and referral | ✅ Each `/summary` visit: `is_emergency`, `is_referral_recommended`, `referral_specialist_name`, `referral_treatment_name` |
| Doctor names | ✅ `/doctors` → `name` |
| Age and sex in patient lists | Coming (Anushka said yes) |
| `None` inside values | ✅ Gone; Temperature now `°F` |

Still open:
- `vital_flags` has no `tier`: are IMPLAUSIBLE readings left out? Which
  `severity` values exist (seen: `ABNORMAL`; our rules look for `CRITICAL`)?
- `bp_sys` / `bp_dia` and `bmi` not seen: BP from the `BP` text, BMI from
  weight and height.

New in the timeline:
- **Document text:** lines such as `Lab Results (Document n)`, `Clinical
  Impression (Document n)`, `Age/Sex (document)` (OCR of uploaded reports;
  1 of 61 patients). Anushka: we may use them. Plan: later, as its own step,
  pull out only fixed lab values (HbA1c, Hb, fasting sugar, cholesterol,
  creatinine, TSH) with name, number, unit and date; never keep or send the
  raw text (it can hold names and phone numbers); show them to the doctor as
  "from a scanned report: please check"; warnings only, never a block.
- **Several visits on one date:** `2 separate visits recorded on this date`,
  then `Visit A of 2`, `Visit B of 2`. The parser must handle it.

## Access

- **URL:** a Cloudflare quick tunnel. It changes on every restart (the one in
  `USAGE.md` was already dead on 2026-10-29; the new one worked). Keep it in
  `backend/.env` as `PATIENT_API_URL`, never in code or docs.
- **Key:** header `X-API-Key`, in `backend/.env` as `PATIENT_API_KEY`. The
  current key is written in `USAGE.md`, which has been shared: a new one has
  been asked for.
- **Speed:** a few seconds per call through the tunnel. Checking 150 patients
  (one `/summary` each, 6 at a time) took about 2.5 minutes. One assessment
  needs 3 calls (`/summary`, `/timeline`, `/snapshot`).

## The endpoints

| # | Endpoint | Status | What it gave |
|---|---|---|---|
| — | `GET /health` | ✅ | `{"status": "ok"}`, no key needed |
| 1 | `GET /patients/{id}/summary` | ✅ | 40 of 40 patients, no errors |
| 2 | `GET /patients` | ✅ | 53,260 IDs |
| 3 | `GET /doctors` | ✅ | 115 doctors: `doctor_id`, `patients` (no names) |
| 4 | `GET /doctors/{id}/patients` | ✅ | Up to 200; `q` (ID prefix) works |
| 5 | `GET /patients/{id}/snapshot` | ✅ | Snapshot, clinical course, rule-based brief, eligibility |
| 6 | `GET /patients/{id}/patient-type` | ✅ | Type and eligibility with reasons, per visit |
| 7 | `GET /patients/{id}/long-term-conditions` | ✅ | Same as in `/summary` |
| 8 | `GET /patients/{id}/medications` | ✅ | Change types seen: `started`, `continued`, `dose_changed` |
| 9 | `GET /patients/{id}/timeline` | ✅ | **Complaints and diagnoses per visit** (below) |
| 10 | `GET /patients/{id}/side-effects` | ✅ | `{medicine: text}`; `use_ai` left off |
| 11 | `GET /patients/{id}/review` | ✅ | 404 when no review is saved, as documented |
| 12 | `POST /patients/{id}/review` | not called | Runs the AI and costs the clinic money |
| — | `GET /patients/{id}` | ❌ 403 | Our key can't call it |

## What we have

| We need | Where | Notes |
|---|---|---|
| Doctors, busiest first | `/doctors` | IDs only |
| A doctor's patients (2+ completed visits, ID search) | `/doctors/{id}/patients` | `patient_id`, `visits`, `last_visit` |
| Age, sex | `/summary` | `sex` is `FEMALE` / `MALE` (USAGE.md says lower case: it isn't) |
| Health history | `/summary` → `health_history` | Same `{present, notes}` shape as ours; 7 conditions, surgeries, hospitalisations, drug allergies, smoking, alcohol, `other_notes` |
| Conditions a doctor recorded | `/summary` → `long_term_conditions` | `name`, `severity`, `status`, `diagnosed_at`; often empty |
| Visits with their doctor | `/summary` → `visits` | **Last 10 only** |
| Vitals per visit | `/summary` → `vitals` | **All visits** (one patient had 23); 6 labels only (below) |
| Current medicines | `/summary` → `ongoing_medicines` | Names only |
| **Chief complaint per visit** | `/timeline` | Text; all visits |
| **Provisional and confirmed diagnosis per visit** | `/timeline` | Text; empty is written `Not Documented` |
| Patient instructions, medicines per visit, follow-ups | `/timeline` | Text |
| Visit count, first and last visit | `/snapshot` → `encounters`, `span` | |
| Eligibility (her part) | `/summary` → `patient_type`, `exercise_suitable`, `exercise_reason`, `types` | Filled for all 40: 25 suitable, 15 not |
| Her clinical flags | `/summary` → `clinical_snapshot.flags` | `level` (high, medium, info), `kind` (followup, risk, pattern, data, medication), `title`, `evidence`. Not the clinic's vital flags |

### The timeline

Plain text, one block per visit, newest first, with fixed labels:

```
PATIENT ID: …
TOTAL VISITS RECORDED: …
DATE: 2026-01-01
  VISIT ID: …
  Chief Complaint (database): …
  Provisional Diagnosis (database): …
  Confirmed Diagnosis (database): …
  Prescription Instructions (database): …
  Vitals (database): …
  Medicines — Prescription (database): …
  Supporting Document: …
  Follow-up Schedule (… scheduled | … completed): …
    • 2026-01-15 | …
```

`TOTAL VISITS RECORDED` matched the number of blocks for all 40 patients.
"Supporting Document" only says whether there is one: we don't use it.

## What's missing

| # | Missing | What we use it for | Without it |
|---|---|---|---|
| 1 | **Sugar and Hb readings.** Vitals only ever carry BP, Pulse, SpO₂, Temperature, Weight, Height: 150 patients checked (29 diabetic), no sugar or Hb for anyone. The clinic stores them in `visit.vitals_json` (`sugar_mg_dl`, `fasting_sugar_mg_dl`, `nonfasting_sugar_mg_dl`, `hb`) | Sugar and Hb reading rules; whether diabetes is under control | Those rules never apply |
| 2 | **The clinic's vital flags** (`visit_vital_flag`: `code`, `severity`, `tier`) | Whether BP or sugar is under control | BP from the readings ourselves; sugar not at all |
| 3 | **Emergency and referral** (`prescription.is_emergency`, `is_referral_recommended`, specialist) | Two severity inputs | Severity rules lose them |
| 4 | **Doctor names** | Doctor picker, "Approved by Dr. …" | IDs shown |
| 5 | Age and sex in patient lists | Doctor's list, review queue | One `/summary` call per patient |
| 6 | `bp_sys` / `bp_dia` when stored separately, `bmi` | BP rule, BMI | BP from the `BP` text; BMI from weight and height |
| 7 | Medicine dose, frequency, duration as fields | Context only | Fine: the timeline text has them |
| 8 | Open disease episodes, care tasks | Context only | Fine without |

Asked of Anushka on 2026-10-29: items 1–4, and a new key.

## Value formats to parse

Seen across 150 patients (`9` = any digit):

| Label | Formats | To handle |
|---|---|---|
| BP | `999/99 mmHg` (most), `999 mmHg`, `999/ mmHg`, `None mmHg` | Systolic only, or missing diastolic: keep systolic, diastolic unknown |
| Pulse | `99 bpm`, `99.9 bpm`, `999 bpm`, `None bpm` | |
| SpO₂ | `99%`, `99.9%`, `None%` | Typing errors such as 970 (already skipped) |
| Temperature | `99.9`, `99`, `None` | No unit |
| Weight | `99.9 kg`, `99 kg`, `9.9 kg`, `None kg` | Implausible values |
| Height | `999.9 cm`, `999 cm`, `99 cm`, `9.9 cm`, `None cm` | `5.4 cm` is probably feet: skip (BMI already needs 100–230 cm) |

`None` comes inside the value: an empty field still gets its label.

## What this means for the build

- `patient_context()` from the API: `/summary` + `/timeline` + `/snapshot`,
  with complaints and diagnoses parsed from the timeline text. Same output
  shape as `app/clinic.py`, so the agent doesn't change.
- New files only: `app/patient_api.py` (client), `app/clinic_api.py` (the five
  functions `doctors`, `patients`, `doctor_name`, `patient_briefs`,
  `patient_context`), `app/source.py` (`CLINIC_SOURCE=api|db`).
  `app/clinic.py` and `app/db.py` stay as they are for when we get the DB back.
- Until items 1–3 come: sugar and Hb rules don't apply, and BP control is
  decided from the readings, not the clinic's flags.
