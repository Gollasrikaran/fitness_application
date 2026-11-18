# Patient Intelligence API: what it covers for the agent testbed

We no longer read the clinic database directly. All patient data and analysis
come from the Patient Intelligence API (deployed by Anushka). This file
compares what the API gives with what the testbed reads today
(`CLINIC_DATA_WE_USE.md`). It also lists what's missing and the open
questions.

Sources: her `USAGE.md`, and the live `/openapi.json`, checked on 2026-10-28.
On that date most response schemas showed only `"string"`, so the field lists
below come from USAGE.md and still need checking against a real response.

## Access

- **URL:** a Cloudflare tunnel. It changes when the API restarts, and the API
  is only up while her machine is on. On 2026-10-28 it answered at first, then
  returned 530 (the machine behind the tunnel wasn't answering).
- **Key:** every endpoint except `/health` needs the `X-API-Key` header. Keep
  it in `backend/.env` as `PATIENT_API_KEY`, never in code or docs.
- **Endpoints:** the key works only on the 12 endpoints below. Every other
  request returns 403.

## Endpoints we can use

| # | Endpoint | Use for the testbed |
|---|---|---|
| 1 | `GET /patients/{id}/summary` | **Main source**: one patient's record and her analysis |
| 2 | `GET /patients` | Not needed (all IDs, with no filters) |
| 3 | `GET /doctors` | The doctor picker |
| 4 | `GET /doctors/{id}/patients` | A doctor's patient list (`q` = ID prefix, `limit` ≤ 200) |
| 5 | `GET /patients/{id}/snapshot` | Flags, visit count, first and last visit, rule-based brief |
| 6 | `GET /patients/{id}/patient-type` | Her eligibility, with the reasons per visit |
| 7 | `GET /patients/{id}/long-term-conditions` | Also inside `/summary` |
| 8 | `GET /patients/{id}/medications` | Medicine changes per visit |
| 9 | `GET /patients/{id}/timeline` | Plain text: might be useful for the doctor chat |
| 10 | `GET /patients/{id}/side-effects` | Optional; leave `use_ai` false |
| 11 | `GET /patients/{id}/review` | Her saved AI analysis (free); optional |
| 12 | `POST /patients/{id}/review` | **Don't use**: it runs the AI and costs the clinic money |

These endpoints are on the server, but our key can't call them: `GET /patients/{id}` ("Get
Patient"), `POST /refresh`, `POST /ai-assist`, `POST /chat`, `GET /faq`,
`POST /graph-sync` and `GET /settings`.

## Available: what we need and where it comes from

| We need | From the API | Notes |
|---|---|---|
| Doctors, busiest first | `/doctors` → `doctor_id`, `patients` | IDs only, no names |
| A doctor's patients with 2+ completed visits, search by ID prefix, up to 200 | `/doctors/{id}/patients` → `patient_id`, `visits`, `last_visit` | Same rules as ours |
| Age, sex | `/summary` → `age_years`, `sex` | `sex` is `male` / `female` (we used `M` / `F`) |
| Health history (7 conditions, surgeries, hospitalisations, drug allergies, smoking, alcohol) | `/summary` → `health_history` | Same `{present, notes}` shape as ours |
| Conditions a doctor recorded | `/summary` → `long_term_conditions` (`name`, `severity`, `status`, `diagnosed_at`) | Same as ours |
| Last 10 visits, with each visit's doctor | `/summary` → `visits` (`visit_id`, `visit_date`, `doctor_id`) | Dates and doctors only |
| Vitals per visit | `/summary` → `vitals[].readings` (`label`, `value`, `date`, `source`) | Text such as `"130/80 mmHg"`: we parse the numbers |
| Current medicines | `/timeline` → the latest visit's `Medicines — Prescription` lines | Since 2026-11-16. `/summary` → `ongoing_medicines` lists every medicine ever prescribed, so we don't use it |
| Visit count, first and last visit | `/snapshot` → `encounters`, `span` | |
| **Eligibility (her part)** | `/summary` → `patient_type`, `exercise_suitable`, `types` | New: we didn't have this before |
| Clinical flags | `/snapshot` → `flags` (`level`, `title`, `evidence`, `kind`) | A different format from our vital flags |

## Not available

In order of importance for exercise plans.

| # | What we use today | Where it was | What it's used for | If it's missing |
|---|---|---|---|---|
| 1 | **Diagnoses per visit** (provisional, confirmed) | `prescription` | Main source of condition codes (knee OA, BP, diabetes…) | Condition codes come only from long-term conditions and health history; many patients get fewer or no codes |
| 2 | **Chief complaint and duration per visit** | `visit` | Warning complaints (chest pain, dizziness, breathlessness), complaints from the last 6 months, knee or back pain | Severe cases could be missed: a safety gap |
| 3 | **Vital flags** (`code`, `severity`, `tier`) | `visit_vital_flag` | Whether BP or sugar is under control | We'd work it out from the readings ourselves (needs item 4) |
| 4 | **The full list of vitals labels** | `vitals_json` keys | The BP rule, sugar, Hb, BMI | We need the exact labels to parse (BP, fasting sugar, random sugar, Hb, weight, height, BMI, pulse, SpO2) |
| 5 | **Emergency and referral flags** | `prescription.is_emergency`, `is_referral_recommended`, specialist | Severity: an emergency or referral sends the patient to the doctor | Severity rules lose two inputs |
| 6 | Doctor names | `"user"` | The doctor picker, "Approved by Dr. …" on the plan page | IDs shown instead of names |
| 7 | Age and sex in patient lists | `patient` | The doctor's list and review queue | One `/summary` call per patient (up to 200 per list) |
| 8 | Patient instructions and follow-up date on prescriptions | `prescription` | Context for the AI and the doctor chat | Less context |
| 9 | Follow-ups (pending, missed, emergency) | `followup_schedule` | Context and severity | May be partly in `snapshot.flags` (kind `followup`) |
| 10 | Open disease episodes, open care tasks | `patient_disease_journey`, `care_task` | Context | Less context |
| 11 | Medicine dose, frequency, duration | `prescriptionitem` | Context only | Fine without |
| 12 | Preferred language, registration date | `patient` | Not used in plans | Fine without |

Items 1, 2 and 5 could all come from one change: the visit fields in
`/summary` (or opening `GET /patients/{id}` to our key, if it has them).

## Questions for Anushka

### Missing data
1. What does `GET /patients/{patient_id}` return? If it's the full record
   (diagnoses, complaints), can our key be allowed on it?
2. If not, can each visit in `/summary` include `chief_complaint`,
   `complaint_duration`, the provisional and confirmed diagnoses,
   `is_emergency`, `is_referral_recommended`, the referral specialist,
   `patient_instructions` and `follow_up_at`?
3. Can `/summary` include the raw vital flags (`code`, `severity`, `tier`,
   `metric`, `value`, date) from the last 5 visits?
4. What `label` values can a vitals reading have? Are BP systolic and diastolic
   ever separate readings?
5. Can `/doctors` include the doctor's name, and `/doctors/{id}/patients`
   include age and sex?

### Rules, so our numbers match
6. Does `/doctors/{id}/patients` leave out under-18s, and deleted, demo and
   merged patients?
7. Is a "completed visit" `status = 'COMPLETED'` and not deleted?
8. Are `vitals` in `/summary` limited to the last 10 visits? Our BP rule takes
   any reading from the last 90 days.
9. If a visit has more than one prescription, which one is used?

### Her analysis
10. What decides `exercise_suitable` (the types and terms behind `Yes` / `No`)?
    When it's `null` (unclassified), should we treat the patient as eligible or
    not?
11. Is `exercise_suitable` about the whole patient, or only the main type?
    For example, Musculoskeletal "Yes" with a heart condition as a second type.

### Running it
12. Is a fixed URL planned? With the tunnel, the URL changes on every restart.
13. When is the API expected to be up? A doctor pressing "Generate plan" needs
    it then.
14. Can the docs have typed response schemas, so the fields show in `/docs`?
15. Can the current key be replaced, since it's written in USAGE.md, which has
    been shared?

## Next steps (testbed)

- [ ] Anushka restarts the API and sends the URL and a new key; both go in
      `backend/.env`.
- [ ] Call `/summary` for one patient and check the field names against this
      file. Print names only, no patient values.
- [ ] Get answers to questions 1–5 (the missing data).
- [ ] Rewrite `app/clinic.py` to call the API, keeping the same output shape so
      the rest of the agent doesn't change.
- [ ] Use `exercise_suitable` as the eligibility gate before drafting (tracker,
      step 0).
- [ ] Try step 4 (rules by BP reading) on real patients.
