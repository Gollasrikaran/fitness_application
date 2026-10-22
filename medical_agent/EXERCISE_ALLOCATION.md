# How exercises are allotted

When a patient saves their profile, the backend picks their exercises with
fixed rules (no AI). The result is only a **draft**: a doctor has to approve
it before the patient sees anything.

The code is in `backend/app/agent/plans.py`, plus one helper,
`approved_exercises()`, in `backend/app/agent/context.py`. Everything is read
from the database tables `conditions`, `exercises` and `safety_rules`.

**In one line:** throw out what's unsafe for any of the patient's
conditions, rank the rest by how useful they are for any of their conditions
(with "careful" ones last), and take the top few at their normal doses.

Below is the whole process for one real patient.

## Example: Priya (knee pain + feeling low, age 28, beginner)

### The data the code starts from

The `safety_rules` table has one row per condition and exercise. For each
pair it says whether the exercise is **safe**, **modify** (okay, but
carefully) or **avoid**, and how useful it is for that condition
(**rank 1 = most useful**). The `exercises` table has each exercise's
normal starting dose.

For Priya's two conditions:

| Exercise | Knee pain | Feeling low | Default dose |
|---|---|---|---|
| Walking | safe, rank 1 | safe, rank 1 | 1 × 1 km |
| Glute Bridge | safe, rank 2 | safe, rank 4 | 2 × 5 |
| Dead Bug | safe, rank 3 | safe, rank 5 | 2 × 4 |
| Shoulder Circles | safe, rank 5 | safe, rank 3 | 2 × 5 |
| **Running** | **modify**, rank 12 | safe, rank 2 | 1 × 1 km |
| Ankle Circles | safe, rank 4 | safe, rank 6 | 2 × 5 |
| Wrist Circles | safe, rank 6 | safe, rank 7 | 2 × 5 |
| Neck Hold | safe, rank 7 | safe, rank 8 | 2 × 5 s |
| Seated Side Stretch | safe, rank 8 | safe, rank 9 | 2 × 10 s |
| Calf Stretch | safe, rank 9 | safe, rank 10 | 2 × 10 s |
| Hamstring Stretch | safe, rank 10 | safe, rank 11 | 2 × 15 s |
| **Thigh Stretch** | **modify**, rank 11 | safe, rank 12 | 2 × 15 s |

Both conditions are "supported", not "refer", so the rules are allowed to
draft a plan.

### Step 1: Remove unsafe exercises

`approved_exercises()` in `context.py`:

```python
if not conditions or any(c.bucket == "refer" for c in conditions):
    return []                                   # heart problem etc. → nothing allowed

for ex in all exercises:
    by_condition = rules for this exercise, one per condition
    if set(by_condition) != set(codes):         # a condition has no rule → out
        continue
    if any(r.verdict == "avoid" ...):           # any condition says avoid → out
        continue
    notes = [notes from "modify" rules]         # keep it, but remember the warning
    approved.append({..., "verdict": "modify" if notes else "safe"})
```

For Priya, nothing says "avoid", so **all 12 stay**. Running and the thigh
stretch are marked "modify" because knee pain says so.

If she had a "refer" condition (heart problem, pregnancy, recent surgery,
and so on), **nothing** would be allowed, and the doctor would have to write
her plan.

### Step 2: Each exercise's best rank

`_usefulness()` in `plans.py` asks the database for the **lowest rank across
her conditions**:

```sql
select activity_type, min(usefulness_rank) from safety_rules
where condition_code in ('arthritis_knee', 'depression') and verdict != 'avoid'
group by activity_type
```

| Exercise | Knee rank | Low-mood rank | Best (min) |
|---|---|---|---|
| Walking | 1 | 1 | **1** |
| Running | 12 | 2 | **2** |
| Glute Bridge | 2 | 4 | **2** |
| Dead Bug | 3 | 5 | **3** |
| Shoulder Circles | 5 | 3 | **3** |
| Ankle Circles | 4 | 6 | **4** |
| … | | | |

The idea: if an exercise is a top pick for **either** of her problems, it's
worth including.

### Step 3: Sort

`starter_exercises()` in `plans.py`:

```python
approved.sort(key=lambda e: (e["verdict"] == "modify",           # 1st: safe before modify
                             ranks.get(e["activity_type"], 99),  # 2nd: best rank
                             by_type[e["activity_type"]].priority_order))  # 3rd: tiebreak
```

Python sorts by the first key, then the second, then the third. `False`
sorts before `True`, so every "safe" exercise comes before every "modify"
one.

| Order | Exercise | modify? | best rank | priority |
|---|---|---|---|---|
| 1 | Walking | no | 1 | 1 |
| 2 | Glute Bridge | no | 2 | 2 |
| 3 | Dead Bug | no | 3 | 3 |
| 4 | Shoulder Circles | no | 3 | 4 |
| 5 | Ankle Circles | no | 4 | 6 |
| … | … | | | |
| 11 | **Running** | **yes** | 2 | 5 |
| 12 | **Thigh Stretch** | **yes** | 11 | 10 |

Running has a good rank (2, because it helps low mood) but drops to near the
bottom because it's "modify" for her knee. Dead Bug and Shoulder Circles tie
on rank 3, so priority order decides it: Dead Bug's 3 beats Shoulder
Circles' 4.

### Step 4: Take the top N

```python
EXERCISES_BY_EXPERIENCE = {"beginner": 4, "intermediate": 5, "active": 7}
count = EXERCISES_BY_EXPERIENCE[profile.experience]   # beginner → 4
approved[:count]                                      # first 4 of the sorted list
```

Result: Walking, Glute Bridge, Dead Bug, Shoulder Circles.

### Step 5: Set the doses

```python
amount = default_amount                              # from the exercises table
if older and amount - step >= step:                  # age >= 60 only
    amount = amount - step                           # one step easier
```

Priya is 28, so she gets the normal doses:

| Exercise | Dose |
|---|---|
| Walking | 1 × 1 km |
| Glute Bridge | 2 × 5 |
| Dead Bug | 2 × 4 |
| Shoulder Circles | 2 × 5 |

That's the draft the doctor sees for her.

## Age and BMI rules (provisional)

These are placeholder values so we can build and test. **The doctor decides
the real ones.** They're the constants `OLDER_AGE`, `HIGH_BMI` and
`HIGH_IMPACT` at the top of `plans.py`.

- **Age 60 or more, or BMI 30 or more:** running is left out.
- **Age 60 or more:** every dose starts one step lower (for example, glute
  bridge 2 × 5 becomes 2 × 3, and walking 1 km becomes 0.8 km).

When one of these rules changes a draft, the draft says so to the doctor.

## When the patient says "too hard"

The patient ticks the exercises that are too hard (none ticked means all of
them) and can give a pain score.

- **Pain 7 or more:** no easier plan is made. It goes straight to the doctor
  as a case, because that's a medical question, not a dose question.
- **Otherwise,** each ticked exercise goes down one step: 5 reps becomes 3,
  or if it's already at the lowest amount, one set is removed. If it can't
  go any lower, it's flagged for the doctor.

Code: `easier_exercises()` in `plans.py`.

## When the patient adds a new condition

Any exercise in their current plan that's unsafe for the new condition is
removed and replaced with the next best safe one (picked the same way as
above). Exercises that are still safe keep their dose. If the new condition
is a "refer" one, the doctor writes the new plan.

Code: `_redraft_for_conditions()` in `plans.py`.

## Doctor approval, always

Whatever the rules produce is only a draft. The doctor sees it under
**Plan reviews** in the doctor portal and can approve it, edit it and then
approve, or reject it. The patient sees a plan only after the doctor
approves it.

## Where the data first came from

The three tables were filled from copies of the main app's files in
`backend/data/` (`conditions.csv`, `safety_grid.csv`,
`activity_taxonomy.csv`) when the database was set up. The app itself only
reads the database. None of this data has been clinically reviewed yet.
