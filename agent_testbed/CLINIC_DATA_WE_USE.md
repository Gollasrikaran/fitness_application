# Clinic data the agent testbed uses

For cross-checking against the dataanalysis service, before we switch from
reading the clinic database directly to the deployed analysis URL.

Today the testbed reads the clinic Postgres database **read-only**: every
transaction is opened READ ONLY, and all queries are fixed SQL in
`agent_testbed/backend/app/clinic.py`. Nothing is ever written to the clinic
database. Below is every table and column we read, with the filters, so the
analysis service can confirm it gives the same data (or tell us where it
differs).

## Rules that apply to every query

| Rule | SQL | Please confirm |
|---|---|---|
| A "live" patient | `patient.deleted_at IS NULL AND NOT patient.is_demo AND patient.merged_into_patient_id IS NULL` | Is this the right way to leave out deleted, test and merged records? |
| Adults only | `patient.age_years >= 18` | Is `age_years` kept up to date? |
| A visit that counts | `visit.deleted_at IS NULL AND visit.status = 'COMPLETED'` | Are other statuses ever clinically complete? |
| The patient's doctor | `visit.assigned_doctor_user_id` → `"user".id` with `role = 'DOCTOR'` | Is this the right doctor link? |
| Recent visits | The patient's latest **10** counting visits, newest first (by `visit.created_at`) | |
| Recent vital flags | Flags from the latest **5** counting visits, leaving out `tier = 'IMPLAUSIBLE'` | Are the flag rules current? |

## What we read

### Doctors (`GET /doctors`)
- `"user"`: `id`, `first_name`, `last_name`, `specialization`, `role = 'DOCTOR'`.
- Joined to `visit` (`assigned_doctor_user_id`, `patient_id`, `deleted_at`) to count distinct patients per doctor, busiest first. Doctors with no visits are left out.
- Also a single doctor's name by id (`"user".first_name`, `last_name`, `role = 'DOCTOR'`), shown on the patient's plan page.

### Patient list (`GET /patients`)
- `visit`: `patient_id`, `created_at`, `status`, `deleted_at`, `assigned_doctor_user_id`. Patients with at least 2 counting visits (with this doctor, when one is chosen), most recently seen first, up to 200.
- `patient`: `id`, `age_years`, `sex`, and the keys of `health_history_json` marked `present` among: hypertension, diabetes, thyroid, heart_disease, asthma, high_cholesterol, tuberculosis.
- Search: by the start of `patient.id`.
- Also age and sex for a list of patient ids (the doctor's review queue).

### One patient's record (`patient_context()`, used by the assessment, the plan draft and the doctor chat)

| What | Table and columns | Filter |
|---|---|---|
| About the patient | `patient`: `id`, `age_years`, `sex`, `preferred_language`, `created_at`, `health_history_json`, `long_term_conditions` | Live patient |
| Visit totals | `visit`: count, first and last `created_at` | Counting visits |
| Recent visits | `visit`: `id`, `created_at`, `chief_complaint`, `complaint_duration`, `vitals_json`; doctor name from `"user"` via `assigned_doctor_user_id` | Latest 10 counting visits |
| Diagnoses and alerts | `prescription`: `id`, `visit_id`, `created_at`, `provisional_diagnosis`, `confirmed_diagnosis`, `is_emergency`, `is_referral_recommended`, `referral_specialist_name`, `referral_treatment_name`, `patient_instructions`, `follow_up_at` | On those 10 visits, `deleted_at IS NULL`. If a visit has several, we keep the latest |
| Medicines | `prescriptionitem`: `prescription_id`, `medication_name`, `dosage`, `frequency`, `duration`, `notes` | On those prescriptions |
| Vital flags | `visit_vital_flag`: `recorded_at`, `metric`, `code`, `severity`, `value` | Latest 5 counting visits, `tier <> 'IMPLAUSIBLE'` |
| Conditions a doctor recorded | `patient_condition`: `severity`, `status`, `diagnosed_at`; `long_term_condition.name` | `deleted_at IS NULL` |
| Follow-ups | `followup_schedule`: counts by `status` (`PENDING`, `MISSED`), next due and last missed `scheduled_date`, count of `is_emergency` | All for the patient |
| Open disease episodes | `patient_disease_journey`: `parent_visit_date`, `chief_complaint`, `confirmed_diagnoses_json`, `status` | `status IN ('OPEN', 'ACTIVE_FOLLOWUP')` |
| Open care tasks | `care_task`: `task_type`, `priority`, `status`, `due_date` | `deleted_at IS NULL`, `status IN ('OPEN', 'CLAIMED')` |

**From `vitals_json` we use these keys only:** `bp`, `bp_sys`, `bp_dia`, `pulse`, `spo2`, `temp_f`, `temp_c`, `sugar_mg_dl`, `fasting_sugar_mg_dl`, `nonfasting_sugar_mg_dl`, `hb`, `weight_kg`, `height_cm`, `bmi`.

**From `health_history_json`**, items marked `present` (with their `notes`): the 7 conditions above, plus surgeries, hospitalisations, drug_allergies, smoking, alcohol.

### Worked out by us, not read

These are computed in our code from the data above, so they don't need to come from the service, but they depend on its fields:
- **BMI:** latest `weight_kg` ÷ latest `height_cm`² (height must be 100–230 cm).
- **Whether BP or sugar is under control:** from the vital flags. Not under control if the latest reading is flagged HIGH or CRITICAL (`BP_SYS_*`, `BP_DIA_*`, `*SUGAR_MG_DL_*`), or any reading in the last 5 visits is CRITICAL.
- **Recent complaints:** chief complaints from the last 6 months.
- **Condition codes:** matched from the diagnoses, complaints, condition lists and questionnaire with our own alias file.

## What we never read

Patient names, phone numbers, addresses, government IDs, family links,
uploaded documents and photos, OCR'd lab reports (`document_extraction`),
consultation audio or video, staff passwords and logins. Doctor names are read
(staff).

## What we need from the deployed service

1. **JSON over HTTPS**, not a dashboard page, for:
   - the list of doctors, as above;
   - a doctor's patients (adults, 2+ counting visits, search by id prefix);
   - one patient's full record, as in the table above;
   - age and sex for a list of patient ids, and a doctor's name by id.
2. **The same filters** as the "Rules that apply to every query" table, or a note on where the service's rules differ, so our numbers match hers.
3. **Read-only access** with an API key or other login. The data is real patients' health records.
4. **Stable field names**, with dates as `YYYY-MM-DD`, and response times of a few seconds or less: one "Generate plan" reads one patient's record once.

## Questions for the cross-check

1. Are the "live patient", "counting visit" and "patient's doctor" rules above right?
2. Is `visit_vital_flag` (with `tier`, `severity`, `code`) still how the clinic flags vitals? Have the codes changed?
3. Can a visit have more than one prescription? We keep the latest.
4. What shape do `health_history_json` and `long_term_conditions` have now? We expect `{key: {present, notes}}` and a list of condition names.
5. Does the service already have a "clinical snapshot" or review we could use instead of rebuilding parts of it (`clinical_snapshot.py`, `review_rules.py` in dataanalysis)?
