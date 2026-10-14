# Medical agent (prototype)

A chat agent for patients that decides, on every message, whether it can help
with self-care or must forward the problem to a doctor. Doctors see the
forwarded cases in a queue and send back a plan, which the patient and the
agent then follow.

Standalone: nothing here imports the main app in `../app`. The condition list,
exercise catalogue and safety grid are copies of the main app's CSVs
(`backend/data/`).

```
medical_agent/
  backend/    FastAPI + SQLAlchemy  (port 8000)
  frontend/   React + Vite          (port 5174)
```

## Run it

**Backend** (first time: create the venv and `.env`):

```powershell
cd medical_agent\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # then fill in DATABASE_URL, SUPABASE_URL, the service role key, OPENROUTER_API_KEY
uvicorn app.main:app --reload --port 8000
```

Tables and reference data are created automatically on first start. API docs:
http://127.0.0.1:8000/docs

**Frontend** (second terminal):

```powershell
cd medical_agent\frontend
npm install
copy .env.example .env.local    # then fill in VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
npm run dev                     # patients: http://localhost:5174   doctors: http://localhost:5174/doctor
```

**Tests** (the LLM is faked, so they're free): `cd backend` then `pytest`.

## Login (Supabase Auth)

Supabase Auth owns accounts: signup, email verification, login and password
reset all happen in the browser through `supabase-js`, and users appear on the
Supabase **Authentication** page. The backend verifies the access token
Supabase issues (`app/auth.py`, via the project's public signing keys) and
keeps its own `users` row per account holding the **role**.

| | Patient app (`/`) | Doctor portal (`/doctor`) |
| --- | --- | --- |
| Sign up | Yes, with email verification | No: created by an admin |
| Log in / forgot password | Yes | Yes |
| Wrong account type | Signed out with "use the doctor portal" | Signed out with "not a doctor account" |

Create a doctor (admin only, uses the service role key):

```powershell
cd backend
python scripts\create_doctor.py doctor@example.com "Dr Asha Rao"
```

New emails get a verified account and a one-time temporary password; an
existing account is promoted. The backend enforces roles on every request, so
the portal check in the browser is a convenience, not the protection.

**Supabase dashboard settings:**

- Authentication -> Sign In / Providers -> Email: keep **Confirm email** on.
- Authentication -> URL Configuration: Site URL `http://localhost:5174`, and
  add `http://localhost:5174/**` to Redirect URLs (verification and reset
  links come back here).
- Supabase's built-in email sender is heavily rate-limited and meant for
  testing; connect your own SMTP (Authentication -> Emails) before real users.

Our tables live in the `public` schema next to Supabase's own `auth` schema.
On Postgres the backend enables Row Level Security on each of them, so the
anon key the browser holds can't read them through Supabase's Data API.

## Database

`DATABASE_URL` in `backend/.env`. Unset = a local SQLite file
(`backend/medical_agent.db`). For Postgres:
`postgresql+psycopg://user:password@host:5432/dbname`. Tables are created with
`create_all`; switch to Alembic migrations before the schema needs to change
under real data.

## How a chat turn is decided

```
patient message
  │
  ├─ 1. Red-flag scan (red_flags.py, English + Hinglish + Devanagari)
  │      emergency (chest pain, can't breathe, fainting, stroke signs,
  │      bladder/bowel loss, self-harm, serious injury)
  │        → fixed "call 112/108" reply (Tele-MANAS 14416 for self-harm)
  │        → urgent case for a doctor. The LLM is never called.
  │
  ├─ 2. Hard rules → the turn MUST go to a doctor
  │      • a "refer" condition (heart, pregnancy, recent surgery, …)
  │      • a priority red flag (fever, can't bear weight, night pain,
  │        hot swollen joint, medicine questions, …)
  │      • progress: pain ≥ 8 this week, or average pain up ≥ 2 vs last week
  │
  ├─ 3. LLM (OpenRouter) gets the full patient context and recent chat and
  │      returns JSON: self_care | clarify | doctor, a reply, a hand-off
  │      summary for the doctor, and facts to remember.
  │      It can escalate; it can never overrule steps 1–2.
  │
  └─ 4. Checks on the output
         • stated pain ≥ 7 → doctor
         • suggested exercises outside the patient's safety grid are dropped
         • a reply naming an unapproved exercise is replaced with a safe one
         • doctor decision → open case (or update the open one)
```

The agent's context on every turn (`agent/context.py`, also visible to the
patient in the sidebar and to the doctor on the case page):

- profile (age, sex, height, weight, BMI, activity level) and conditions
- exercises the safety grid approves for **all** their conditions
- this week vs last week: active days, totals per exercise, average and
  highest pain, and warning signals
- facts remembered from earlier chats (so older context survives after the
  messages scroll out of the last-20 window)
- the open doctor case and the latest doctor plan

## Before real patients use this

- **Clinical sign-off.** The red-flag list, the escalation thresholds (pain
  7/8, +2 trend) and the safety grid (`reviewer` = "not clinically reviewed")
  all need a clinician's review.
- **Doctor notification.** Escalations land in the doctor queue (refreshes
  every 15 s) and are logged. There is no email/SMS/push yet; emergencies in
  particular should page someone.
- **Doctor verification.** Admins create doctor accounts by hand; record and
  check each doctor's medical registration number.
- **Data protection.** Chats contain health data: add consent, retention and
  deletion, and host the database in India (DPDP Act).
