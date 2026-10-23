# Build plan: doctor-approved exercise plans

Status as of 2026-10-23. Tick items off as they land.

## What we are building

Decided with the CEO:

- **No chatbot for patients.** Patients are mostly in rural areas and phone their doctor. They only need a page that shows the exercise plan their doctor approved.
- **The agent works on the doctor's side.** It reads the patient's clinic record, works out what problem the patient has and how severe it is, and then either:
  - drafts an exercise plan, or
  - sends the patient straight to a doctor when the case is too severe for an AI draft.
- **A doctor approves every plan.** Nothing reaches the patient until a doctor approves it. There is no automatic progression: any change to a plan is a new draft that needs approval again.
- **Rules first, AI second.** Fixed rules decide safety. The AI can make a decision stricter, never milder.

```
Doctor selects a patient and clicks "Generate plan"
  → load record            clinic DB, read-only, no AI
  → rule screen            no AI: refer conditions, critical vitals, recent emergencies → severe
  → AI assessment          structured output: conditions, problem, body area, severity, evidence
  → finalise               rules: unknown code → other_unlisted; refer → doctor; can only raise severity
      ├─ severe     → "Doctor must write plan" in the doctor's queue (no AI draft)
      └─ not severe → AI picks exercises from the allowed list → code checks it → pending draft
  → doctor reviews         approve / edit / reject (a reason is required to reject)
  → approved plan          shown on the patient's plan page
```

## Data sources

| Source | Access | What we use from it |
|---|---|---|
| Clinic DB (Supabase, `CLINIC_DATABASE_URL`) | Read-only | Patient record: visits, vitals, diagnoses, medicines, follow-ups, alerts |
| College reference DB (Supabase, `REFERENCE_DATABASE_URL`, new) | Read-only. We may not create tables there. | `conditions`, `safety_grid`, `activity_taxonomy` (instructions, GIFs), `video_catalog`, `rag_chunks` |
| Our CSVs (`backend/data/*.csv`) | In the repo | The 11 conditions and 108 rule rows the college DB does not have |
| Temp DB (`TEMP_DATABASE_URL`) | Read and write | Everything we own: merged reference tables, assessments, drafts, approved plans, cases, chat history |

### How the reference data merges

Checked on 2026-10-23: the college DB is an exact subset of our CSV.
- All 17 of its conditions match ours, with the same bucket.
- All 132 of its rule rows agree with ours.
- The doses of all 12 exercises match.
- There are no conflicts, so we merge as follows.

| What | From the college DB | From our CSV |
|---|---|---|
| Conditions | 17 | +11: `prediabetes`, `high_cholesterol`, `obesity`, `arthritis_knee`, `pcos`, `depression`, `anxiety`, `diabetes_controlled`, `bp_controlled` (supported); `diabetes`, `high_bp` (refer) |
| Safety rules | 132 | +108 rows for those 11 conditions, plus `usefulness_rank` |
| Exercises | 12, with step-by-step instructions (10 of 12) and demo image URLs (10 of 12) | The same 12 doses, plus synonyms |

The college DB's demo GIFs are paths inside her app (`/static/demos/...`), so we can't load them. All of its `video_catalog` URLs are empty. We use the instructions and images only.

**Rule:** if the two ever disagree on a verdict, the stricter one wins (avoid > modify > safe). The disagreement is logged.

**Not used from the college DB:**
- `users`, the token tables, `user_program`, `activity_logs`, `progression_history`, `override_consents`, `rehab_chat_log`, `rehab_memory` and `user_profiles`.
- All of them are empty. They belong to a self-signup fitness app and aren't linked to clinic patients.

**Clinical review:** every exercise and rule row in both sources is marked `product-team (not clinically reviewed)`. A clinician must sign them off before real patients receive plans.

## Already done

- [x] Clinic record reader with visit-by-visit grouping: diagnosis, all medicines, instructions and follow-up per visit (`app/clinic.py`). The code is in place but not committed.
- [x] Doctor-mode chat about a patient (`agent/nodes.py` → `chat`).
- [x] Rule-based mapping from the clinic record to condition codes (`agent/conditions.py`).
- [x] Temp DB tables `plans`, `plan_proposals` and `cases`, with approve and reject endpoints (`store/`, `app/main.py`).
- [x] Rule-based starter plan from the safety grid (`store/plans.py` → `starter_exercises`).

## Work to complete

### Phase 1: Connect the college reference DB (done 2026-10-23)
- [x] `REFERENCE_DATABASE_URL` is in `backend/.env` (git-ignored), with a placeholder in `.env.example`. `store/reference.py` reads it once at startup through a read-only connection.
- [x] Added `instructions`, `images`, `max_sets`, `max_amount`, `per_side`, `rest_seconds` and `prescription_type` to `exercises`, and `notes` to `conditions`.
- [x] `store/seed.py` rebuilds the reference tables on every start: our CSVs, with the college DB merged on top and the stricter verdict winning. Every disagreement is logged.
- [x] If the college DB can't be reached, it falls back to the CSVs alone with a warning. Instructions and images are then empty until the next start.
- **Result:** 28 conditions (20 supported, 8 refer), 240 rules (191 safe, 46 modify, 3 avoid), 12 exercises (10 with instructions and images). No disagreements between the two sources.

### Phase 2: Save chat history in the temp DB (done 2026-10-23)
- [x] New `messages` table: thread, mode, patient, doctor, role, text, the agent's decision, and time (`store/messages.py`).
- [x] `MemorySaver()` replaced with LangGraph's `PostgresSaver` on `TEMP_DATABASE_URL`. Its 4 tables are kept in the `agent_tmp` schema. The package is `langgraph-checkpoint-postgres==3.2.0`.
- [x] `GET /chat/history` returns a saved conversation, and the chat loads it on open, so a page reload shows it again.
- **Result:** tested across a backend restart. The agent recalled a fact from the earlier conversation, and both turns were in `messages`.

### Phase 3: Remove the patient chatbot (done 2026-10-23)
- [x] Deleted patient mode from the following:
  - `agent/main.py`: the graph is now `load_context → chat`
  - the `safety_screen`, `emergency`, `supervisor`, patient-facing `plan` and `doctor_handoff` nodes
  - `PATIENT_CHAT` and `SUPERVISOR` in `agent/prompts.py`
  - `agent/red_flags.py`
  - the "too hard" flow in `store/plans.py` (`request_easier`, `easier_exercises`, `exercises_named`) and exercise synonyms
  - the patient chat UI in the frontend
- [x] Kept the doctor chat, `clinic.py`, `conditions.py`, the rule floor in `routing.py` (`condition_floor`), and the rule plan engine (`request_plan`, `sync_conditions` and `starter_exercises`, for phase 5).
- [x] The Patient tab now shows only the approved plan (`GET /patients/{id}/plan`, `PatientPlan.jsx`). Phase 7 adds instructions and images.
- [x] Updated `README.md` and `FEATURES.txt`.
- Doctor cases (`cases`) stay for now: existing cases can still be closed, but nothing opens new ones until phase 5.

### Phase 4: Assessment (built 2026-10-23, waiting on the BP/sugar decision below)

**What was built:**
- `data/condition_aliases.csv` (133 rows, from the real clinic wording) maps clinic wording to our codes. `data/warning_complaints.csv` lists the complaints that send a patient to a doctor. Both are loaded into the temp DB at startup. **They need clinical review.**
- `agent/conditions.py` holds no condition lists: it only matches the record against the aliases. It reads the clinic's condition list, the health history, diagnoses (last 10 visits) and chief complaints (last 6 months). Unknown clinic conditions are reported as unmapped, never dropped.
- `agent/assess.py`: the AI reads the same record and picks codes from the 28, quoting the record. A quote not found in the record, or a code outside the list, is dropped. Vital readings are left to the clinic's flags, and the AI's "not listed" findings become concerns for the doctor.
- `agent/routing.py` → `finalize`: merges both sources and decides severity. Which conditions need a doctor comes from the database bucket.
- Saved in the `assessments` table, with `POST /patients/{id}/assess` and `GET /patients/{id}/assessment`.
- Fixed along the way: the clinic connection pool now tests connections, because the pooler drops idle ones during AI calls.

**Dry run on 50 real patients:** 37 severe, 8 moderate, 5 mild. The AI ran on all 50, and 7 AI findings were dropped by the checks. Reasons for severe: BP not under control 18, AI rated severe 24 (the only reason for 3 patients), not listed 12 (mostly thyroid/asthma), sugar not under control 9, critical vital 7, warning complaints 13.

**Decided (2026-10-23):** BP or sugar counts as "not under control" when the **latest reading** is flagged HIGH or CRITICAL by the clinic, or **any reading in the last 5 visits is CRITICAL**. ELEVATED and LOW flags don't count; before this, any sugar flag did. The AI can only say "not controlled" when the record's own words say so ("uncontrolled DM"). Re-run on 50 patients: 38 severe, 6 moderate, 6 mild. "BP not under control" fell from 18 to 11 and "sugar not under control" from 9 to 1. The largest reason is now the AI rating a case severe (24; the only reason for 5 patients).

Original plan for this phase:
This builds the first half of the new pipeline: record → rules → AI → final assessment.
- [ ] New `Assessment` structured output from the AI:
  - condition codes, chosen only from the merged list
  - a one-line problem summary and body area
  - severity: `mild`, `moderate` or `severe`
  - evidence lines quoted from the record (visit date + field)
  - any missing information
- [ ] **Rules before the AI:** the `conditions.py` mapping and the `routing.py` floor (critical vitals, recent emergency visits).
- [ ] **Rules after the AI:**
  - Codes outside the merged list are dropped. If nothing valid is left, the code is `other_unlisted`.
  - Any `refer` condition makes the case severe.
  - The AI can add conditions and raise severity, never remove or lower them.
- [ ] If the AI fails, use the rule-only result. If that has no supported condition, send the patient to a doctor.
- [ ] Save every run in a new `assessments` table holding inputs, AI output, final result and model name.
- [ ] Use `rag_chunks` as background for less common problems: filter by `condition_code`, then keyword search. Vector search would need the embedding model behind the 1536-dimension vectors, which is unknown.
- **Done when:** running it over 50 real patients (read-only) gives a sensible condition and severity for each, with evidence, and every refer condition is marked severe.

### Phase 5: Plan drafting
- [ ] **Severe:** create a "doctor must write plan" item (`plan_proposals` with `source = "doctor"`, linked to the assessment). There is no AI draft.
- [ ] **Not severe:** the AI picks and orders exercises from the allowed list and writes a short reason for the doctor. Code then enforces the rules:
  - An exercise marked `avoid` for **any** of the patient's conditions can never appear.
  - Exercises marked `modify` keep the grid's note in the draft.
  - Doses start at `default_sets` / `default_amount` and never exceed `max_sets` / `max_amount`.
  - Only the 12 known exercises are allowed.
- [ ] If the AI fails or breaks a rule, use the existing rule-only `starter_exercises` draft.
- [ ] Add `assessment_id`, `severity` and `source = "ai"` to `plan_proposals`.
- **Done when:** tests prove that no draft ever contains an `avoid` exercise or a dose above the maximum.

### Phase 6: Doctor screen
Flow: the doctor selects a patient and clicks **Generate plan**. The draft opens for editing (exercises, sets, amounts, instructions), and the doctor clicks **Approve**.
- [ ] **Endpoints:**
  - `POST /patients/{id}/assess` runs the pipeline.
  - `GET /review-queue` returns pending drafts and severe patients, oldest first.
- [ ] **Review card:** the assessment with its evidence, the draft exercises with grid notes, and approve / edit / reject. Approve and reject already exist.
- [ ] **Doctor-written plan form:** an exercise picker limited by the grid. Picking an `avoid` exercise is blocked, and `modify` shows its note.
- [ ] Keep the doctor chat next to the review card.

### Phase 7: Patient plan page
- [ ] `GET /patients/{id}/plan` returns the latest **approved** plan only. It never returns drafts or the assessment.
- [ ] **Read-only patient tab, in English:** each exercise with sets × amount, per side, rest time, step-by-step instructions and demo images, plus the approving doctor and date. Nothing else.
- [ ] Large text and simple layout, readable on a low-end phone.
- [ ] If there is no approved plan: "Your doctor hasn't shared a plan yet."

### Phase 8: Testing before real use
- [ ] Unit tests for the rules: no `avoid` exercises, dose caps, refer → doctor, unknown → `other_unlisted`, the AI can never lower severity.
- [ ] A read-only dry run over a sample of real patients, with a report of severity counts and the most common conditions.
- [ ] A doctor reviews a batch of drafts, and their edits and rejections are recorded.
- [ ] A clinician signs off the merged conditions, rules and exercises.

## Decisions (2026-10-23)

1. **What starts an assessment:** the doctor selects a patient and clicks "Generate plan", edits the draft, then approves it.
2. **Patient access:** a patient tab that only displays the doctor-approved plan.
3. **Language:** English.
4. **`rag_chunks` embeddings:** the model is unknown, so we use condition-code filtering plus keyword search.
5. **Severe cases:** they go straight to the doctor, with no AI suggestion.
6. **More exercises:** not now.

## Out of scope for now

- Lab results from OCR'd reports (`document_extraction`).
- Neo4j: only the dataanalysis dashboard uses it.
- Patient feedback ("too hard", "done") and automatic progression.
