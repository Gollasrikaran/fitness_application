# Known issues: to fix later

Found while building and testing (phase 7 and 8, 2026-10-26). None of these
are fixed yet. Each has what we saw, why it matters, and a proposed fix. Fixes
that make a safety rule less strict need a go-ahead first.

The dry-run figures come from `backend/scripts/dry_run.py` on 50 real patients
(seed 8, 2026-10-26; assessments saved in the temp DB as `doctor_id = dry-run-p8`).

## Bugs

### 1. "Knee joint pain" makes a patient severe
- **Seen:** the alias file has `knee joint pain → arthritis_knee` and `joint pain → other_unlisted` ("joint not named: doctor decides"). Text such as "Knee joint pain since 1 month" matches both, so the patient also gets `other_unlisted`, which is a refer condition, so the case is severe.
- **Impact:** in the dry run, 2 of 50 patients were severe for this reason alone and would otherwise have had an AI draft; a third had it on top of other reasons.
- **Where:** `agent/conditions.py` → `rule_findings()` / `match_text()`; `data/condition_aliases.csv` lines for `joint pain`, `polyarthralgia`.
- **Proposed fix:** when one alias phrase matches words inside a longer alias phrase that matched the same text, keep only the longer match. Add a test with "knee joint pain". Makes the rules less strict: needs a go-ahead.

### 2. The backend doesn't check that the doctor is the patient's doctor
- **Seen:** `/chat`, `/chat/history`, `/patients/{id}/assess` and `/proposals/{id}/approve` / `reject` accept any `doctor_id` with any `patient_id`. Any text works as a doctor id (test runs used `e2e-test`, `dry-run`). One saved conversation (2026-10-24) is Dr. Srinivas Manchinella asking about an 85-year-old patient he has 0 visits with. The screen can't do this (it lists only the doctor's own patients), so it most likely came from a direct API call during testing.
- **Impact:** a doctor (or anything calling the API) could read and act on another doctor's patient. Matters once there is a real login.
- **Proposed fix:** on those endpoints, refuse unless the doctor id is a real `DOCTOR` in the clinic DB with at least one visit with this patient: "This patient isn't one of this doctor's patients." The dry-run script calls the agent code directly, so it keeps working.

### 3. The chat's two stores can drift apart
- **Seen:** each turn is kept twice: LangGraph's checkpoint (what the AI remembers) and `agent_tmp.messages` (what the screen shows). `agent/main.py` → `run_turn()` writes `messages` only after the AI has answered and the checkpoint is saved.
- **Impact:** if that write fails, the agent remembers a turn the screen never shows.
- **Proposed fix:** write both in one place, or rebuild the screen's history from the checkpoint; or at least log and retry a failed `save_turn`.

### 4. The chat memory grows forever
- **Seen:** the checkpoint keeps every message of a conversation. Only the last 20 (`HISTORY_FOR_CHAT` in `agent/nodes.py`) are sent to the AI.
- **Impact:** none today (8 messages saved). Long conversations will make each checkpoint bigger.
- **Proposed fix:** trim the stored messages to the last N, or summarise older ones.

## Decisions needed (from the dry run)

### 5. Old pregnancies still count
- **Seen:** diagnoses are read from the last 10 visits whatever their date. 2 patients are still "Pregnant / recently had a baby" from "26 wks pregnancy" / "30 wks pregnancy" recorded 10–11 months ago. The same applies to `recent_surgery` and `acute_injury`.
- **To decide:** how long time-bound conditions count, for example pregnancy up to 12 months after the last antenatal entry, surgery and injury 3 months.
- **Where:** `agent/conditions.py` (complaints already use `RECENT_DAYS`; diagnoses don't).

### 6. The AI overrules the clinic's BP flags
- **Seen:** 4 patients were severe only because the AI rated them severe. In 3, the AI's reason was "elevated blood pressure" while the clinic's flags say BP is under control (the rule decided on 2026-10-23). The 4th was a good catch (pancytopenia, cirrhosis, severe anaemia).
- **To decide:** keep it (the AI may only make things stricter), or tell the AI in the prompt that BP and sugar control are decided by the flags, so it can't raise severity on BP alone.

### 7. Dizziness and tingling send many patients to a doctor
- **Seen:** a warning complaint in the last 6 months made 13 of 50 patients severe; for 4 it was the only reason. Dizziness was the most common (10 patients), often everyday wording ("Dizziness, acidity", "Weakness dizziness"); numbness or tingling next (5).
- **To decide (clinical):** whether dizziness and tingling alone should stop an AI draft, or only show as a concern on it. `data/warning_complaints.csv`.

### 8. Language of the patient page
- **Seen:** the plan says English (decided 2026-10-23), but in the clinic DB 55,242 patients prefer Hindi, 1,973 Marathi and 9 English. The clinic's own advice sheets (`visit_advice_sheet`) are stored in English and Hindi.
- **To decide:** raise with the CEO before patients use the page.

## Alias gaps (data, needs clinical review)

### 9. Wording the aliases don't cover
- `LBA` and `acute lumbago` (low back ache): should map to `chronic_back_pain`.
- `HT` as short for hypertension (only `htn` is covered): should map to `bp_any`.
- `DJD` on its own, with no joint named.
- Most other unmatched diagnoses are outside exercise (skin, ENT, fevers, infections), which is correct.

## Quality, not safety

### 10. AI drafts vary little
- **Seen:** all 11 AI drafts in the dry run start with Walking. The 4 patients with no condition we track all got the same five exercises (Walking, Shoulder Circles, Ankle Circles, Wrist Circles, Neck Hold).
- **Proposed fix:** look at the draft prompt and the order of `candidates()` once a doctor has reviewed some drafts (`GET /review-summary`).

### 11. Testbed controls at phone width
- **Seen:** at 360px the testbed's top bar cuts off the "Doctor" button and the patient dropdown sticks out of its card. The patient plan page itself is fine.
- **Proposed fix:** let the top bar wrap and give the pickers `min-width: 0`. Testbed only.

## Housekeeping

### 12. Data files not in git
- `backend/data/*.csv` (conditions, safety grid, exercises, aliases, warning complaints) are untracked. The app can't start correctly from a fresh clone without them. Commit them.

### 13. Old test rows in the temp DB
- From 2026-10-21, before phase 5: 2 approved plans, 2 pending "doctor must write" drafts, 2 open cases, and the 8 chat messages above. Harmless; the 2 plans are useful for testing the patient page. Delete them before any real use.
