# Agent testbed

A place to build and try the agent on real clinic data, without touching the
live website. No login: toggle **Patient** or **Doctor**, pick from the
dropdowns, and chat. The right-hand panel shows exactly what the agent knows
about the chosen patient (listed in `FEATURES.txt`).

- **Patient mode:** pick a patient and chat as them.
- **Doctor mode:** pick a doctor, then one of their patients, and ask about
  that patient.

The chat is answered by the agent in `backend/agent/` (LangGraph):

```
patient: load_context → safety_screen ─┬─ emergency (fixed reply, no AI)
                                       └─ supervisor ─┬─ chat (or one clarifying question)
                                                      ├─ plan (placeholder for now)
                                                      ├─ doctor_handoff
                                                      └─ emergency
doctor:  load_context → chat (answers the doctor about the patient)
```

| File | Job |
| --- | --- |
| `agent/state.py` | `AgentState` |
| `agent/main.py` | Builds the graph; `run_turn()` is what `POST /chat` calls |
| `agent/nodes.py` | One function per node |
| `agent/routing.py` | The routing rules (the AI rates, these rules decide) |
| `agent/conditions.py` | Clinic record → our condition codes (provisional, needs clinical review) |
| `agent/red_flags.py` | Emergency and priority red-flag rules (from medical_agent) |
| `agent/prompts.py`, `agent/llm.py` | Prompts; the OpenRouter model (`LLM_MODEL`, default `openai/gpt-4o-mini`) |

Each reply in the testbed shows the route and, under it, the supervisor's
ratings and the rules that applied. Conversations are kept in memory until
the backend restarts.

## The agent's own data (temporary database)

Plans, plan drafts and doctor cases are saved in a temporary database
(`TEMP_DATABASE_URL`: medical_agent's test database), in its own schema
`agent_tmp`, so nothing else there is touched. Tables are created on start.

| Code | Job |
| --- | --- |
| `store/models.py` | Tables: reference data (conditions, exercises, safety rules) + `cases`, `plan_proposals`, `plans` |
| `store/plans.py` | The rule-based plan engine (ported from medical_agent): starter, easier, update |
| `store/cases.py` | Doctor cases: one open case per patient |
| `store/seed.py` | Creates the schema and tables, loads `data/*.csv` |

Every plan is a draft until a doctor approves it. In **Doctor** mode the side
panel shows the patient's draft and open case, with Approve / Reject / Close.

| Route | |
| --- | --- |
| `GET /patients/{id}/agent` | Approved plan, pending draft, open case |
| `POST /proposals/{id}/approve` / `reject` | `{doctor_id, instructions?, note?}` (reject needs a note) |
| `POST /cases/{id}/close` | `{doctor_id, note?}` |

## Data

Reads the live clinic database (the one `dataanalysis/` uses), **read-only**:
every transaction is opened READ ONLY, so the database refuses any write.
Only adults (18+) are listed; deleted, test and merged records are left out.
Patient names, phones, addresses and IDs are never read.

## Run

Backend (port 8001):

```powershell
cd agent_testbed\backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # then set CLINIC_DATABASE_URL (as DATABASE_URL in dataanalysis\.env) and OPENROUTER_API_KEY
.venv\Scripts\python -m uvicorn app.main:app --port 8001 --reload --reload-dir app --reload-dir agent --reload-dir store
```

Frontend (port 5175):

```powershell
cd agent_testbed\frontend
npm install
npm run dev
```

Open http://localhost:5175.

## API

| Route | What it returns |
| --- | --- |
| `GET /doctors` | Doctors who have seen patients, busiest first |
| `GET /patients?doctor_id=&search=&limit=` | Adult patients, most recently seen first; with `doctor_id`, only that doctor's |
| `GET /patients/{id}/context` | Everything the agent knows about the patient |
| `POST /chat` | `{mode, patient_id, doctor_id, message}` → `{reply, route, reason, ...}` |
