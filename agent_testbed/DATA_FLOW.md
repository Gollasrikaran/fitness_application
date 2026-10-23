# Data flow: where the agent's data comes from

How a patient's clinic record becomes a list of our condition codes, and
from there a decision on whether the AI may draft an exercise plan or a doctor must write it.

Last checked against the code and the databases: 2026-10-23.

## The four sources

| Source | Env var | Access | What we take | Read when |
|---|---|---|---|---|
| Clinic DB (live clinic Supabase) | `CLINIC_DATABASE_URL` | **Read-only** (every transaction is READ ONLY) | The patient's record | Every assessment and every doctor-chat turn |
| Reference DB (a colleague's Supabase) | `REFERENCE_DATABASE_URL` | **Read-only**. We may not create tables there. | Conditions, safety grid, exercises with instructions and images | **Once, at startup** |
| Our CSV files (`backend/data/`) | — | In the repo | Our conditions and safety grid (a superset of the reference DB's), the alias file, the warning complaints | **Once, at startup** |
| Temp DB (ours) | `TEMP_DATABASE_URL` | Read and write, schema `agent_tmp` | The merged reference data, plus everything the agent produces | Always |

At runtime the agent **never reads the reference DB or the CSVs directly**. It reads the merged copy in the temp DB.

```
startup:      Reference DB ─┐
                            ├─ merge (store/seed.py) ─→ Temp DB reference tables
              data/*.csv ───┘

per patient:  Clinic DB ─→ patient record ─→ aliases (rules) ─→ AI ─→ safety rules ─→ assessment
                           (app/clinic.py)   (agent/conditions.py)  (agent/assess.py) (agent/routing.py)  (Temp DB)
```

## 1. Startup: building the reference data

`store/seed.py` runs on every start. It drops and rebuilds these temp DB tables, so the reference DB and CSV edits flow in on the next restart:

| Temp DB table | Built from | Rows (2026-10-23) |
|---|---|---|
| `conditions` | `data/conditions.csv` + reference `conditions` | 28 (20 supported, 8 refer) |
| `safety_rules` | `data/safety_grid.csv` + reference `safety_grid` | 240 (191 safe, 46 modify, 3 avoid) |
| `exercises` | `data/activity_taxonomy.csv` + reference `activity_taxonomy` | 12 (10 with instructions and images) |
| `condition_aliases` | `data/condition_aliases.csv` only | 133 |
| `warning_complaints` | `data/warning_complaints.csv` only | 22 |

**Merge rules** (`store/seed.py`, reading via `store/reference.py`):
- A condition, rule or exercise found in either source is kept.
- If both have a rule or a condition bucket, the **stricter one wins** (avoid > modify > safe; refer > supported). Every disagreement is logged at startup. On 2026-10-23 there were none: the reference DB's 17 conditions and 132 rules all match our CSV.
- Doses (default and maximum sets and amounts) come from our CSV. Exercise **instructions** and **images** (`demo_images`) come from the reference DB.
- If the reference DB can't be reached, startup continues on the CSVs alone with a warning. Exercises then have no instructions or images until the next start.

**What we don't use from the reference DB:**
- `demo_gif`: paths inside the colleague's app (`/static/demos/...`), which we can't load.
- `video_catalog`: every URL is empty.
- `rag_chunks`: 834 chunks of medical reference text. Not used yet.
- `users`, the token tables, `user_program`, `activity_logs` and similar: all empty, and they belong to a separate fitness app.

## 2. What we read from the clinic DB

All queries are in `app/clinic.py` (`patient_context()`). They are fixed SQL: the AI never writes queries. Patient names, phone numbers, addresses, government IDs and uploaded documents are **never selected**.

Scope: the patient's last **10 completed visits**. Vital flags come from the last **5** visits, leaving out readings flagged IMPLAUSIBLE.

### Structured columns (fixed values)

| Table.column | What it holds | How it's matched |
|---|---|---|
| `patient_condition` → `long_term_condition.name` | Conditions a doctor formally recorded, from a fixed list of 21 names ("Hypertension", "Diabetes Mellitus"…). Only ~659 records exist. | Exact name, alias source `long_term_condition` |
| `patient.long_term_conditions` | The patient's own condition list (JSON), with the same 21 names | Exact name, alias source `long_term_condition` |
| `patient.health_history_json` | Registration questionnaire: `hypertension`, `diabetes`, `thyroid`, `heart_disease`, `asthma`, `high_cholesterol`, `tuberculosis` marked present | Exact key, alias source `health_history` |

These cover general medical conditions only, not knee, back or neck problems.

### Free text (typed by doctors and staff)

| Table.column | What it holds | How it's matched |
|---|---|---|
| `prescription.provisional_diagnosis` / `confirmed_diagnosis` | The diagnosis, e.g. "DJD knee spine", "htn, t2dm". ~10,400 different wordings. | Alias phrases (source `text`), then the AI. From all 10 visits. |
| `visit.chief_complaint` | Why the patient came, e.g. "knee pain". ~41,700 different wordings; 13,886 visits have a complaint but no diagnosis. | Alias phrases, then the AI. **Only visits in the last 6 months** (`RECENT_DAYS`). Also checked for warning complaints. |
| `prescriptionitem.medication_name` | Medicines on each prescription | The AI only (e.g. Metformin → diabetes) |

**Knee, back, neck and injury conditions come almost entirely from free text.**

### Used for the decision, not to find conditions

| Table.column | Use |
|---|---|
| `visit_vital_flag.code` / `severity` | The clinic's own flags (`BP_SYS_HIGH`, `SUGAR_MG_DL_CRITICAL`…): whether BP or sugar is under control, and critical readings |
| `visit.vitals_json` | Readings: BP, sugar, weight, height (BMI ≥ 30 → `obesity`) |
| `prescription.is_emergency` | An emergency visit sends the patient to the doctor |

Also read, for the doctor chat and the side panel: complaint duration, instructions to the patient, follow-up dates, referrals, open episodes and care tasks.

## 3. The alias file: clinic wording → our codes

`backend/data/condition_aliases.csv` is the bridge. The clinic DB has no condition codes, while the reference data uses them everywhere. Columns: `source, phrase, code, note`.

| source | Matches against | Rule | Example |
|---|---|---|---|
| `long_term_condition` | Clinic condition names | Exact name, ignoring case | `Hypertension → bp_any` |
| `health_history` | Questionnaire keys | Exact key | `thyroid → other_unlisted` |
| `text` | Diagnoses and complaints | The phrase appears as **whole words, in order** | `oa knee → arthritis_knee` matches "bilateral oa knee" but `knee pain` won't match "kneepain" |

- **Special codes:** `bp_any` and `diabetes_any` aren't condition codes. They mean "BP / diabetes present, control to be decided", and the safety rules turn them into `bp_controlled` / `high_bp` or `diabetes_controlled` / `diabetes`.
- **Checked at startup:** an alias pointing at an unknown code is dropped with a warning.
- **Unmapped means flagged, not dropped:** a clinic condition or questionnaire item with no alias is reported as "unmapped" and becomes `other_unlisted`, so a doctor decides.
- **Complaint-only:** a code found only from a complaint (a symptom, not a diagnosis) is marked `complaint_only`, so the doctor sees it's a best match.
- **Problems we have no exercises for:** shoulder, foot, heel, general joint pain, thyroid, asthma and similar map to `other_unlisted`, so a doctor writes the plan.

`backend/data/warning_complaints.csv` lists complaint phrases such as chest pain, breathlessness, dizziness, fainting, palpitations, numbness and seizure. One in a complaint from the last 6 months sends the patient to a doctor.

**Both files are provisional and need clinical review**, like the safety grid. To support new wording, add a row and restart the backend.

## 4. The assessment, step by step

`POST /patients/{id}/assess` → `agent/assess.py` → `run_assessment()`.

| Step | Code | AI? | What happens |
|---|---|---|---|
| 1. Load the record | `app/clinic.py` | No | Section 2 |
| 2. Rules | `agent/conditions.py` → `rule_findings()` | No | Alias matching, warning complaints, BMI, unmapped list |
| 3. AI | `agent/assess.py` → `_ask_ai()` | **Yes** | Reads the record, picks codes from the 28 and quotes the record for each, and writes a one-line problem, body area, severity, concerns and missing information |
| 4. Checks | `agent/assess.py` → `_check()` | No | Drops an AI code outside the list, and an AI quote not found word for word in the record. AI `other_unlisted` becomes a concern, not a condition. An AI "not under control" for BP or sugar stands only if the quote itself says so ("uncontrolled DM"); otherwise the flags decide. |
| 5. Safety rules | `agent/routing.py` → `finalize()` | No | Merges the findings and decides severity (below) |
| 6. Save | `store/assessments.py` | No | `assessments` table: codes, evidence, severity, reasons, the AI's raw answer, dropped findings, model |

**Severe** (a doctor writes the plan, with no AI draft) if any of these is true:
- any final code has bucket `refer` in the `conditions` table (heart, pregnancy, recent surgery, acute injury, neurological, `high_bp`, `diabetes`, `other_unlisted`)
- BP or sugar not under control: the **latest reading is flagged HIGH or CRITICAL**, or **any reading in the last 5 visits is CRITICAL** (ELEVATED and LOW don't count)
- a critical vital flag, or an emergency visit, in the recent visits
- a warning complaint in the last 6 months
- the AI rated the case severe
- the AI failed **and** the rules found nothing

The AI can add conditions and raise severity, but never remove a condition or lower severity. If the AI call fails, the rules' result is used alone.

## 5. What the AI sees, and what it costs

Each assessment sends:
1. **Fixed instructions + the 28 conditions** (~1,320 tokens, the same for every patient)
2. **What the rules already found**
3. **The record as JSON** (`_record()`): age and sex, BMI, recorded conditions, condition list, health history, other history, the last 10 visits (complaint, diagnosis, medicines, vitals, instructions, follow-up), vital flags, alerts

Measured on 20 real patients (about 4 characters per token):

| Part | Avg tokens | Max |
|---|---|---|
| Fixed instructions + condition list | ~1,320 | ~1,320 |
| Medicines (repeated in every visit) | ~270 | ~700 |
| Other visit fields | ~150 | ~440 |
| Rest of the record | ~190 | ~370 |
| Vitals | ~90 | ~300 |
| Complaints + diagnoses (free text) | ~45 | ~130 |
| **Total input** | **~2,060** | **~3,000** |

Output is roughly 300–500 tokens. Model: `LLM_MODEL` (default `openai/gpt-4o-mini`) via OpenRouter. The alias matching, warnings and safety rules use **no tokens**.

Nothing is cached: every click runs the AI on the whole record again. Proposed savings, not yet built:
- Reuse the last assessment when the record hasn't changed.
- Put the variable parts (date, rule findings) after the fixed instructions, so OpenAI's automatic 50% prompt-caching discount applies.
- List each medicine once instead of in every visit, and drop vitals, patient instructions and doctor names from the AI's copy.

## 6. The doctor chat

`POST /chat` → `agent/main.py` → graph `load_context → chat`.

- `load_context` (`agent/nodes.py`): reads the same clinic record, runs the **rules only** (no AI) for `AGENT_CONDITIONS`, and adds the latest saved assessment, the approved plan, any pending draft and any open case.
- `chat`: one AI call with the doctor-chat prompt, the record (`record_block()` in `agent/prompts.py`) and the last 20 messages.
- Every turn is saved in `messages`, and LangGraph's checkpointer keeps the conversation in its `checkpoint*` tables, so chats survive restarts.

## 7. What's stored in the temp DB

| Table | Holds | Lifetime |
|---|---|---|
| `conditions`, `safety_rules`, `exercises`, `condition_aliases`, `warning_complaints` | Reference data (section 1) | Rebuilt on every start |
| `assessments` | Every assessment run, with evidence and the AI's raw answer | Kept |
| `messages` | Every doctor-chat turn | Kept |
| `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` | LangGraph's conversation memory | Kept |
| `plan_proposals` | Plan drafts waiting for a doctor | Kept |
| `plans` | Doctor-approved plans: what the patient sees | Kept |
| `cases` | Concerns passed to a doctor (from the old patient chat) | Kept |

## 8. Not read or not used

- Lab results from scanned reports (`document_extraction`): raw OCR text that includes personal details; only 107 documents exist.
- Neo4j: only the dataanalysis dashboard uses it, and it holds a copy of data already in the clinic DB.
- The reference DB's `rag_chunks`, `demo_gif` and `video_catalog` (section 1).
