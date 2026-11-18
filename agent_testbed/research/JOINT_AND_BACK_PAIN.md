# Knee, back and hand pain: exercise research

Researched 2026-11-17 for dashboard patient #32 (`bdbdc1f3`, `TESTING_CHECKLIST.md`
Round 2). Same layout as `HYPERTENSION.md` and `DIABETES.md`: Part A is what
the evidence says, Part B is what we propose (to decide; nothing is built).
Sources at the end.

Scope reminder: a colleague decides who may exercise; we decide what and how
much. Our codes: `arthritis_knee` ("Knee pain"), `chronic_back_pain`,
`arthritis_hip`, `spondylosis`, `carpal_tunnel` ("Wrist pain") are supported;
an unnamed joint (`joint pain`, `arthralgia`) goes to `other_unlisted` (a
doctor writes the plan).

## Why now

The three patients tested so far (#29, #30, #33) had BP or diabetes, the two
conditions we researched. #32 has none of them: her record is knee, back,
hip and hand pain, with tingling. The safety grid has rows for knee and back
pain since the start, but they were never researched: almost every row says
"Gentle, low-load movement with no specific concern". The knee ranks are
already sensible (Seated Knee Straightening, Walking, Side Leg Raise first);
the back-pain ranks are not (Dead Bug, a floor exercise, 1st; Neck Hold 5th;
Sit to Stand 14th). Checked in `data/safety_grid.csv` on 2026-11-17.

## Patient #32 (bdbdc1f3): what our app sees today

46 F, 23 visits (11 Jun → 7 Oct 2026), BMI about 21.5, BP normal. No
long-term condition recorded.

| In the record | Our app today | Why |
|---|---|---|
| "OA knee" (25 Jun), "Knee arthitis" (25 Aug), knee pain in complaints | `arthritis_knee` | aliases `oa knee`, `knee arthitis`, `knee pain` |
| "Low back ache" (4 visits, confirmed 19 and 24 Sep) | `chronic_back_pain` | alias `low back ache` |
| "hip pain" (24 Sep) | `arthritis_hip` | alias `hip pain` |
| "Multiple joint pain under evaluation" (19 Sep) | `other_unlisted` → **doctor** | alias `joint pain` (joint not named) |
| **Tingling** in the right hand (13 Jul), both legs and thighs when sitting (24 Jul, 4 Aug) | warning complaint → **doctor** | within the 183-day window (105–127 days old) |
| "Hand pain" (7 Oct, latest visit), "Rt hand shoulder pain" | **nothing** | no alias for hand or shoulder pain |
| "Muscular cramp", "Muscle spasm", "Arthritis" (no joint), "Leg pain" | nothing | no alias |

**Expected: doctor**, for two reasons that are both right: tingling (legs
and hand) and an unnamed "multiple joint pain". Not assessed yet in the temp
DB (checked 2026-11-17, read only).

**What the evidence below adds:** leg tingling *with back pain*, worse on
sitting, can be a nerve root problem (sciatica-type). That is a reason for a
doctor, not for an exercise draft, so our current rule is the safe one.

## Part A: what the evidence says

### Knee osteoarthritis

- **Exercise is a core treatment in every major guideline**: OARSI 2019
  (core: education + structured land-based exercise, ± weight management),
  ACR 2019 (strongly recommended), NICE NG226 2022 ("for all people with
  osteoarthritis, offer therapeutic exercise tailored to their needs").
- **What kind:** local muscle strengthening (mainly the thigh / quadriceps
  and hip muscles) plus general aerobic activity (walking). NICE gives these
  as examples; OARSI and ACR don't rank one type over another.
- **Pain at the start is expected:** NICE says to tell people that joint
  pain may increase when they start exercising. A commonly used rule in
  physiotherapy (pain-monitoring model; not checked against a source here):
  some pain during exercise is acceptable if it settles by the next day and
  doesn't build up week to week.
- **Weight:** for overweight people any weight loss helps; 10% is better
  than 5% (NICE). Not relevant for #32 (BMI 21.5).
- **Walking aids** (a stick) can be considered (NICE). Supervised sessions
  are a weaker "consider" recommendation; our setting is unsupervised home
  exercise.
- **The clinic's own advice matches:** the physiotherapy note on 25 Jun for
  #32 says "VMO and quadriceps strengthening, ankle pumps, hamstring and calf
  stretching, static cycling 10 min morning and evening" (the record's own
  words, in English and Hindi).

### Chronic low back pain

- **WHO 2023** (first WHO guideline on chronic primary low back pain):
  structured exercise programmes are a conditional recommendation (low
  certainty) for adults, including older people. Types covered: aerobic,
  strength, stretching, yoga, Pilates, tai chi. The supporting review found
  exercise probably reduces pain and disability (moderate certainty); no
  type was clearly best.
- **NICE NG59** (not read again today; known content): consider group
  exercise; stay active; don't offer bed rest.
- **"Chronic primary"** means no specific cause found. Back pain with
  nerve signs (leg tingling or numbness, weakness, pain below the knee) is a
  different group, and guidelines send it for assessment first. Red flags
  (general knowledge, to confirm with the doctor): numbness in the saddle
  area, bladder or bowel change, leg weakness getting worse, night pain with
  weight loss or fever.

### Hand osteoarthritis and hand pain

- **EULAR 2018** (hand OA): exercises to improve function and muscle
  strength and to reduce pain "should be considered for every patient".
  The benefit is small (pain, function, stiffness, grip) with few and minor
  side effects, and it **disappears when people stop**. Trials varied widely
  in type and dose, so EULAR says to tailor the exercises.
- Typical home hand exercises in the trials (to confirm before we write
  steps): making a gentle fist, finger spreads, thumb-to-fingertip touches,
  wrist bends.
- **Hand pain is not always hand OA.** #32's record says "Hand pain" and
  "Rt hand shoulder pain" with tingling in the right hand. Tingling in the
  hand points to a nerve (carpal tunnel, or the neck); a doctor should say
  which before we suggest hand exercises.

### Safety: what the sources agree on

- Exercise is safe and helpful for knee, hip, back and hand OA; serious
  harms are rare.
- Pain that rises a little and settles is acceptable; sharp, swelling, or
  next-day-worse pain means do less.
- Nerve signs (tingling, numbness, weakness) and the back red flags above
  come first: assessment before an exercise plan.
- Kneeling and deep squatting load an arthritic knee most (general
  knowledge). This matters in India, where people squat and sit on the
  floor: our floor rule only applies at 60+ or BMI 30+.

## Part B: what we propose for our app (to decide)

### 1. Keep tingling as a stop (no change)

#32 shows why: leg tingling with back pain may be a nerve root problem. The
open question in `KNOWN_ISSUES.md` #7 (numbness / tingling as a stop or a
concern) should stay "stop" for back or neck patients at least.

### 2. Research-backed ranks and notes for `arthritis_knee`

The `arthritis_knee` ranks already match the evidence (Seated Knee
Straightening 1, Walking 2, Side Leg Raise 3, Sit to Stand 4); keep them.
Proposed changes are notes only:
- Note on Walking for knee pain: "Some knee pain is OK if it settles by the
  next day. If it is worse the next day, walk less."
- Keep the "modify" rows (Wall Sit, Sit to Stand, Single-leg stand, Quad
  stretch, Running).
- Question for the doctor: should Glute Bridge and Dead Bug (floor) be left
  out for knee pain at any age, since getting down to the floor is the hard
  part?

### 3. Research-backed ranks for `chronic_back_pain`

- Rank first: Walking, Marching, Glute Bridge, Sit to Stand, Slow Breathing.
- Add a stop line to every back-pain draft: "Stop and tell your doctor if
  pain spreads down the leg, or the leg tingles or feels weak."

### 4. Hand pain

Options:
- A. **Alias only:** "hand pain" → `other_unlisted` (doctor decides), like
  shoulder pain today. Smallest change; safest.
- B. **New code** `hand_pain` (supported) plus 3 hand exercises (fist,
  finger spread, thumb touch) with grid rows. Only for hand pain with no
  tingling or numbness.

**Recommended: A now, B after the doctor answers question 3 below.** Today
"hand pain" is ignored completely, which is the gap to close.

### 5. Other wording with no alias (from #32)

`muscle spasm`, `muscular cramp`, `leg pain`, bare `arthritis`: decide whether
they map to a code, to `other_unlisted`, or stay ignored. Bare `arthritis`
should probably be `other_unlisted` (joint not named), like `joint pain`.

### 6. Weekly plan (tracker step 5, not built)

What the guidelines suggest, for when the weekly plan is built: strength
work 2–3 days a week, walking most days, start small and build up over
weeks; hand exercises daily (the benefit lasts only while they continue).

## Questions for the doctor

1. Tingling in the legs with back pain: always a doctor first (our rule
   today)? Or only within a shorter window?
2. Knee pain: leave out floor exercises at every age, not only at 60+ /
   BMI 30+?
3. Hand pain without tingling: may the AI draft hand exercises, or always a
   doctor (like shoulder pain)?
4. "Some pain that settles by the next day is OK": may we tell patients
   this on the plan?
5. Are the knee and back ranks in Part B sensible?

## Sources

- OARSI 2019 guidelines, knee/hip/polyarticular OA (Bannuru et al.,
  Osteoarthritis Cartilage 2019;27:1578–89): [PubMed](https://pubmed.ncbi.nlm.nih.gov/31278997/),
  [open copy](https://wrap.warwick.ac.uk/125416/)
- NICE NG226 Osteoarthritis (2022), recommendations 1.3: [NICE](https://www.nice.org.uk/guidance/ng226/chapter/Recommendations),
  [rationale](https://www.nice.org.uk/guidance/ng226/chapter/Rationale-and-impact)
- WHO guideline for non-surgical management of chronic primary low back pain
  (2023): [summary brochure](https://cdn.who.int/media/docs/default-source/mca-documents/ageing/lbp/summary_who_guideline_lower-back-pain_brochure_v7.pdf),
  [supporting review (PubMed)](https://pubmed.ncbi.nlm.nih.gov/37991647/)
- EULAR 2018 hand OA recommendations (Kloppenburg et al., Ann Rheum Dis
  2019;78:16–24): [PubMed](https://pubmed.ncbi.nlm.nih.gov/30154087/),
  [full text](https://ard.bmj.com/content/78/1/16.full)
- Patient record: `patient_dashboard.html` (colleague's dashboard), patient
  `bdbdc1f3`.
