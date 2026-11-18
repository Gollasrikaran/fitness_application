# What our AI reads: Summary + Timeline, not Snapshot

5 November 2026

## In short

The colleague's Patient Intelligence API can give us a patient's record in
three ways: **Summary**, **Timeline** and **Snapshot**. Our AI reads the
**Summary and the Timeline**. We checked whether the Snapshot would be
better. It isn't: it costs about the same, but it holds conclusions instead
of facts, and some of those conclusions were wrong.

**Decision: keep Summary + Timeline for the AI.** The Snapshot may be useful
later for the doctor chat, as background only.

## The three options

| | What it is | Example |
|---|---|---|
| **Summary** | The patient's data from the clinic database, as structured fields | Age, sex, recorded conditions, BP and pulse readings with dates, medicines, the clinic's own alerts on readings |
| **Timeline** | Each visit written out as text | Complaint "Both leg pain, tingling sensation", diagnosis "OA knee", the doctor's note |
| **Snapshot** | The colleague's rules' **interpretation** of the record | A report titled "AI Clinical Review", a short history, which problems are "active", whether exercise suits the patient |

Summary and Timeline are **facts as the clinic recorded them**. The Snapshot
is **someone else's reading of those facts**.

None of these calls costs money. The colleague's paid AI review is a separate
call that we never use.

## What it costs (tokens the AI reads)

Measured on one real patient (65-year-old woman with diabetes, high BP and
knee arthritis, 3 visits) with the AI model's own counter:

| | Tokens |
|---|---|
| Summary + Timeline, as the API sends them | 3,819 |
| Snapshot, as the API sends it | 1,536 |
| **What our AI actually reads** (we keep only the useful parts of Summary + Timeline) | **1,590** |

So in practice **the cost is the same**. Switching to the Snapshot would
save nothing.

Most of the Timeline's size here came from long skin-care notes in Marathi
and Hindi (70% of its tokens). That's where we could save tokens later, not
by switching to the Snapshot.

## Why Summary + Timeline is better for the AI

1. **Facts, not opinions.** For the same patient, the Snapshot got important
   things wrong:
   - it said her knee arthritis was "not recorded since", but the knee is
     her main reason for an exercise plan
   - it listed only her skin condition as "active", and her diabetes and BP
     only as "history"
   - it showed a "BP 140/90 or above" alert, but her BP was never that high
     (128/82, then 116/68)
   - it counted tingling in her legs as a reason exercise **helps**. In a
     diabetic, tingling can be nerve damage, and our rules send it to a doctor
2. **Our safety check needs the clinic's own words.** Every condition the AI
   finds must be quoted word for word from the record, or it's thrown away.
   This stops the AI inventing things. It only works on the original record.
3. **The AI tends to repeat what it's told.** Given a report headed "AI
   Clinical Review", it would likely copy that report's mistakes into its
   assessment.
4. **The Snapshot is missing what our safety rules need:** the readings
   with their dates, the clinic's own alerts, and the full complaints. One
   complaint in its report was cut off mid-word.

## Where the Snapshot could help

Its short history section (about 270 tokens) reads well, for example "BP
128/82 (Aug) → 116/68 (Sep)" and "pain medicines at visit 2". It could help
the AI answer a doctor's question like "how has she been doing?" in the
**doctor chat**, labelled as the colleague's summary. It should **not** be
used to decide plans.

## How we use the colleague's work today

From her Summary we already show the doctor:
- her "can this patient exercise?" screening, with its reason
- her clinical flags (e.g. "Possible neuropathic symptoms")

Both are **information for the doctor only**. They never decide a plan. Her
screening is general research on who benefits from exercise, not a safety
check: for one patient it said "not suitable" only because exercise "neither
helps nor harms" a skin condition.

As always, nothing reaches a patient until a doctor approves the plan.
