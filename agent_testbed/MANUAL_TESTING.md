# Manual testing: patients to try

Real clinic patients picked from the phase 8 dry run (2026-10-26) for testing
the app by hand. The clinic DB is only read; everything you generate or approve
is saved in our temp DB.

Each patient is listed with a doctor whose list shows them (the Doctor tab
lists only patients with 2+ completed visits with that doctor).

## Before you start

```powershell
# Backend (port 8001)
cd agent_testbed\backend
.venv\Scripts\python -m uvicorn app.main:app --port 8001 --reload --reload-dir app --reload-dir agent --reload-dir store

# Frontend (port 5175), in a second terminal
cd agent_testbed\frontend
npm run dev
```

Open http://localhost:5175, click **Doctor**, choose the doctor, type the first
8 characters of the patient id in **Find by patient id**, pick the patient, and
click **Generate plan** (it takes 10–20 seconds).

## Not severe: the AI drafts a plan

Expected: a severity badge (mild or moderate), "AI draft", 3–5 exercises at the
starting doses, "Why this draft", and simple instructions for the patient.

| Patient id | Age, sex | Doctor | Last result | Conditions |
|---|---|---|---|---|
| `8df05662-7ba3-48f8-9e87-d85312579048` | 68 F | Pankaj kumar | moderate | BP and sugar under control |
| `711895b9-fb0f-40dd-8de0-75dbb4768bc1` | 35 F | Aditi Chhonkar | moderate | BP under control |
| `825ce295-03ab-4700-a1ea-d64e64acf131` | 27 F | Shivangi Yadav | moderate | BP under control, PCOD |
| `9fbfeacc-02d4-475d-b43b-864eece7d5fb` | 70 M | Dipali R Patoliya | moderate | Overweight (age 70: no running, lower doses) |
| `336ed3c1-ddea-4e99-9044-8422d60a8125` | 48 M | Dipali R Patoliya | moderate | Overweight |
| `adb32df7-27c0-46af-b8a5-22cc6cd15552` | 28 F | Dipali R Patoliya | mild | none we track |
| `807f7bf8-9c37-4571-a284-b665ee75659e` | 29 F | Dipali R Patoliya | mild | none we track |

The AI reads the record each time, so a rerun can rarely come out different
(for example rated severe). That's expected, not a bug.

## Severe: the doctor must write the plan

Expected: a red "severe" badge, the reasons listed, "Doctor must write" with no
exercises, and the exercise picker to build the plan yourself. These come from
fixed rules, so they give the same result every time.

| Patient id | Age, sex | Doctor | Why severe |
|---|---|---|---|
| `1e0a8c78-382c-4f06-a240-5fe25dc2ea31` | 68 M | Pankaj kumar | BP not under control (clinic flags) |
| `a2e16e3c-0987-4afe-a7eb-f48b49d37115` | 65 M | Aditi Chhonkar | Heart problem; sugar not under control |
| `910a619b-de71-4114-8077-47beb04988e4` | 64 F | Rajiv Khare | Nerve-related problem (cervical myelopathy, radiculopathy) |
| `c0b36697-05c1-4ec6-9a61-ddef14b63a0e` | 65 F | Pankaj kumar | Critical vital reading; dizziness complaint |
| `1a4f74c9-227d-4d23-826a-51b2d7425992` | 46 F | Pankaj kumar | Tingling in a recent complaint (warning complaint) |
| `54d7c7db-c05f-4a30-8500-4f1a54f20024` | 23 F | Dipali R Patoliya | Dizziness in a recent complaint, nothing else |
| `2da101ea-0bd9-4598-b939-0aef0ff3533c` | 25 F | Kruti Balar | Thyroid: not in our list, so a doctor decides |

### Severe because of a known issue (see KNOWN_ISSUES.md)

Use these to see the issues for yourself, and to check them again once fixed.

| Patient id | Age, sex | Doctor | Issue |
|---|---|---|---|
| `882c28d0-ccdf-49aa-9bb0-3f40fa4d1efa` | 63 F | Dipali R Patoliya | #1: "Knee joint pain" also counts as "not listed". Should be an AI draft once fixed. |
| `2f4336f2-8739-4b04-bf8c-df5a2f4391fa` | 68 M | Bhuvnesh Chaturvedi | #1: same knee joint pain bug |
| `c7d30781-3603-4644-90d5-c57c0c36b967` | 36 F | Shivangi Yadav | #5: pregnancy from a diagnosis 10 months ago still counts (also has a critical vital) |
| `0fc77491-d61a-46fe-9f65-8c0b6029ef31` | 37 M | Aditi Chhonkar | #6: the AI rates it severe for "elevated BP" though the flags say controlled. AI-based, so it may differ on a rerun. |

## What to check

**Not severe (AI draft)**
1. Change a dose above its usual maximum: a small orange warning appears, and Approve still works.
2. Add an exercise from "+ Add an exercise": the picker shows each one's verdict for this patient.
3. Remove an exercise, edit the instructions, then **Approve**.
4. Switch to the **Patient** tab, find the same patient: the plan shows your version, with sets and repetitions (or hold time), rest, steps and your note.
5. Back in the Doctor tab, click **Generate plan** again: it asks before replacing, then gives an "update" draft listing what changed.
6. **Reject** a draft: it needs a reason.

**Severe (doctor writes)**
1. The reasons match the table above.
2. Add exercises yourself. One marked avoid, or not reviewed for a condition, shows a warning but doesn't block.
3. Approve, then check the Patient tab shows it.

**Review queue**
- Drafts you generate show at the top of the Doctor tab under "Waiting for your review", oldest first. Clicking one opens that patient.

**Patient tab**
- `17646e7a-3d1b-43fc-8fa8-c486659d3289` already has an approved plan (from earlier testing).
- Any patient you haven't approved a plan for shows "Your doctor hasn't shared a plan yet."
- Narrow the browser to phone width: the plan stays readable in one column.

## After testing

Plans you approve stay in the temp DB, so these patients will then get "update"
drafts and show a plan in the Patient tab. To start a patient over, ask to have
their test rows removed (temp DB only).
