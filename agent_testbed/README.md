# Agent testbed

A place to build and try the agent on real clinic data, without touching the
live website. No login: toggle **Patient** or **Doctor** and pick from the
dropdowns. The plan for what we are building is in `BUILD_PLAN.md`; where every
piece of data comes from (clinic DB, reference DB, CSVs, aliases, what the AI
sees) is in `DATA_FLOW.md`.

- **Patient tab:** pick a patient and see the exercise plan their doctor
  approved. Read-only: patients don't chat with the agent.
- **Doctor tab:** pick a doctor, then one of their patients. Ask the agent
  about that patient, and review plan drafts. The right-hand panel shows
  exactly what the agent knows about the patient (listed in `FEATURES.txt`).

The doctor's questions are answered by the agent in `backend/agent/` (LangGraph):

```
load_context (clinic record, no AI) → chat (answers from the record)
```

| File | Job |
| --- | --- |
| `agent/state.py` | `AgentState` |
| `agent/main.py` | Builds the graph and its memory; `run_turn()` is what `POST /chat` calls |
| `agent/nodes.py` | One function per node |
| `agent/assess.py` | The assessment: rules + AI find the patient's conditions; `run_assessment()` |
| `agent/draft.py` | The plan draft: severe → a doctor writes it; otherwise the AI picks from the allowed exercises and the rules check it; `generate_plan()` |
| `agent/routing.py` | Safety rules: merge the findings and decide whether a doctor must write the plan |
| `agent/conditions.py` | Matches the record against `data/condition_aliases.csv` and `data/warning_complaints.csv` (both need clinical review) |
| `agent/prompts.py`, `agent/llm.py` | The doctor-chat prompt; the OpenRouter model (`LLM_MODEL`, default `openai/gpt-4o-mini`) |

Conversations are saved in the temporary database, so they survive a backend
restart and show again after a page reload.

## The agent's own data (temporary database)

Everything the agent owns is saved in a temporary database
(`TEMP_DATABASE_URL`), in its own schema `agent_tmp`, so nothing else there is
touched. Tables are created on start.

| Code | Job |
| --- | --- |
| `store/models.py` | Tables: reference data (conditions, exercises, safety rules) + `messages`, `cases`, `plan_proposals`, `plans` |
| `store/seed.py` | Creates the schema and tables; rebuilds the reference data from `data/*.csv` merged with the reference DB |
| `store/reference.py` | Reads the reference DB (`REFERENCE_DATABASE_URL`, read-only) |
| `store/plans.py` | The plan safety rules: allowed exercises, the rule-only starter plan, `violations()`; approve / reject |
| `store/messages.py` | Saved chat turns |
| `store/cases.py` | Doctor cases: one open case per patient |

LangGraph's checkpointer keeps its own tables (`checkpoint*`) in the same schema.

Every plan is a draft until a doctor approves it. In the **Doctor** tab the side
panel shows the patient's draft and open case, with Approve / Reject / Close.

## Data

- **Clinic database** (the one `dataanalysis/` uses), **read-only**: every
  transaction is opened READ ONLY, so the database refuses any write. Only
  adults (18+) are listed; deleted, test and merged records are left out.
  Patient names, phones, addresses and IDs are never read.
- **Reference database** (a colleague's), **read-only**, read once at start:
  conditions, safety grid, exercise instructions and images. Without it the
  app runs on `data/*.csv` alone.

## Run

Backend (port 8001):

```powershell
cd agent_testbed\backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # then fill in the database URLs and OPENROUTER_API_KEY
.venv\Scripts\python -m uvicorn app.main:app --port 8001 --reload --reload-dir app --reload-dir agent --reload-dir store
```

Frontend (port 5175):

```powershell
cd agent_testbed\frontend
npm install
npm run dev
```

Open http://localhost:5175.

## Tests

```powershell
cd agent_testbedackend
.venv\Scripts\python -m pytest
```

The plan and severity rules, on an in-memory copy of `data/*.csv`: no database or AI is used.

## API

| Route | What it returns |
| --- | --- |
| `GET /doctors` | Doctors who have seen patients, busiest first |
| `GET /patients?doctor_id=&search=&limit=` | Adult patients, most recently seen first; with `doctor_id`, only that doctor's |
| `GET /patients/{id}/context` | Everything the agent knows about the patient |
| `POST /patients/{id}/assess` | `{doctor_id}` → "Generate plan": runs the assessment (conditions, severity, reasons) and drafts a plan for review → `{assessment, draft}` |
| `GET /patients/{id}/assessment` | The latest assessment |
| `GET /patients/{id}/plan` | The patient's latest approved plan (what the Patient tab shows) |
| `GET /patients/{id}/agent` | Approved plan, pending draft, open case (Doctor tab) |
| `POST /chat` | `{patient_id, doctor_id, message}` → `{reply, conditions}` |
| `GET /chat/history?patient_id=&doctor_id=` | The saved conversation, oldest first |
| `POST /proposals/{id}/approve` / `reject` | `{doctor_id, instructions?, note?}` (reject needs a note) |
| `POST /cases/{id}/close` | `{doctor_id, note?}` |
