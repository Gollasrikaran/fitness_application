# Skin conditions (eczema, fungal infection): exercise research

Researched 2026-11-17 for dashboard patient #31 (`0017c9d8`, eczema) and, in
passing, #33 (`6959e408`, fungal infection with BP). Same layout as the other
research docs: Part A is the evidence, Part B is what we propose (to decide;
nothing is built). Sources at the end.

## Why now

Skin problems are common in the dashboard patients (3 of 5: eczema, tinea,
shingles), but none of our 31 conditions covers skin, and no alias maps any
skin wording. Skin rarely stops exercise, so this is mostly about **advice**
for the patient, not about safety rules.

## Patient #31 (0017c9d8): what our app sees today

36 F, 8 visits (4 Jul → 10 Sep 2026), BMI 22. Eczema at every visit
(diagnosis became "LSC", lichen simplex chronicus, a thickened itchy eczema,
on 10 Sep). Oral steroid courses twice, potent steroid cream 5 times.

Last assessment in the temp DB (16 Nov 2026, read only):

| Result | Why | Our reading |
|---|---|---|
| **Severe** | "Critical vital: TEMP_C_CRITICAL = 34.4" on 3, 13 and 21 Aug | These are **94 °F** entries, almost certainly typing or measuring errors (the colleague's dashboard says "verify"). The clinic's own flag rules call them critical, and our rules trust the clinic's flags |
| `bp_controlled` ("BP under control") | Diagnosis on 14 Jul: "HTn G6A2B1C0" (from a scanned document) | The structured record says "Eczema" that day; the dashboard notes the document disagrees. "G6A2B1C0" is pregnancy history. Whether she has hypertension needs checking. Her BP readings are all normal (120/60 to 128/88) |
| Eczema | **not found** | no alias for eczema, LSC, dermatitis, itching |
| Fever 100.4 °F on 10 Sep | not used | over 2 months old |

So she goes to a doctor because of a data error, not because of her skin.
Two things to raise with the colleague (data, not our rules): the 94 °F
readings flagged critical, and the "HTn" document line.

## Part A: what the evidence says

### Eczema (atopic dermatitis and similar)

- **Exercise is not harmful to eczema and isn't to be avoided.** The
  problem is **sweat and heat**: sweat dries to a salty residue that
  irritates the skin and brings on the itch (National Eczema Association,
  Mayo Clinic).
- Advice the sources agree on:
  - Exercise in a **cool** place or time of day; avoid overheating.
  - **Loose, cotton** clothes; avoid tight or rough fabric that rubs.
  - **Rinse or shower soon after**, warm not hot, 5–10 minutes, then
    **moisturise**.
  - **Drink water.**
  - **During a flare:** lower the intensity; low-sweat exercise
    (stretching, slow walking, breathing) instead of hard workouts. You
    don't need to drip with sweat to benefit.
- No guideline limits exercise *type* for eczema. Friction matters on the
  sore areas (e.g. eczema on the feet and legs, as in #31: long standing or
  walking in tight shoes may rub).

### Fungal infection (tinea / ringworm)

- Grows in **warm, moist** skin folds (groin, inner thighs, feet); people
  who sweat a lot get it more often.
- Advice (Mayo Clinic, AAFP; standard dermatology advice, not trial-tested):
  - **Dry the skin well after exercise or bathing**, the infected area last.
  - **Change sweaty clothes, underwear and socks** soon after exercise.
  - Loose, breathable cotton clothes; no tight synthetic clothes.
  - Don't share towels; wash them after use.
  - Treat athlete's foot too, or it comes back.

### Safety

- Neither eczema nor tinea is a reason to stop an exercise plan.
- Broken, weeping or infected skin, or fever, is a reason to pause and see
  the doctor (general knowledge, to confirm).
- Long courses of oral steroids can affect bones, muscles and sugar; short
  courses don't change exercise (general knowledge). We build no rules on
  medicines; the AI may mention it as a concern.

## Part B: what we propose for our app (to decide)

### 1. A skin condition code

Options:
- A. **Nothing:** skin stays invisible to the rules; the AI may mention it as
  a concern. Today's state.
- B. **New code `skin_condition`** (supported, "Skin problem: eczema or
  fungal infection"), with aliases `eczema`, `dermatitis`, `lsc`, `tinea`,
  `fungal infection`, `ringworm`, `itching`. Every grid row "safe" (no
  exercise is limited), and the advice below as the condition's notes.

**Recommended: B**, because the advice is the point and B gives it a home.
It needs the "condition advice on the plan" gap (`POC_GAPS.md` section 4) to
reach the patient; until then the advice shows to the doctor only.

### 2. The advice text (for the doctor to approve)

> Exercise when it is cool. Wear loose cotton clothes. After exercise, wash
> with lukewarm water, dry well (especially skin folds and feet), change into
> dry clothes and put on your moisturiser. Don't share towels. If the skin is
> broken, oozing or very itchy, do lighter exercise and tell your doctor.

### 3. Shingles (herpes zoster)

#30 had shingles in July. Not an exercise condition after it heals; during
an active rash, rest. Proposed: no code; the AI mentions it if recent.

### 4. Data issues to raise with the colleague (not ours to change)

- 94 °F temperatures flagged `TEMP_C_CRITICAL` (34.4 °C): likely entry
  errors, but they send #31 to a doctor.
- A document diagnosis "HTn G6A2B1C0" taken as the visit's diagnosis when
  the structured record says "Eczema".

## Questions for the doctor

1. Should skin problems get their own code with advice (option B), or stay
   as a note only?
2. Is the advice text in Part B section 2 right, in plain words for the
   patient?
3. Broken or oozing skin: a stop for an AI draft, or a note?
4. #31's 94 °F readings: should a single implausible low temperature still
   send a patient to a doctor? (Today the clinic's critical flag decides.)

## Sources

- National Eczema Association, exercising with eczema: [tips](https://nationaleczema.org/eczema-exercise/)
- Mayo Clinic, can I exercise if I have atopic dermatitis: [expert answer](https://www.mayoclinic.org/diseases-conditions/atopic-dermatitis-eczema/expert-answers/can-i-exercise-if-i-have-atopic-dermatitis/faq-20515224)
- Mayo Clinic, jock itch: [symptoms and causes](https://www.mayoclinic.org/diseases-conditions/jock-itch/symptoms-causes/syc-20353807)
- American Family Physician, superficial fungal infections (1998): [AAFP](https://www.aafp.org/pubs/afp/issues/1998/0701/p177.html)
- Patient record: `patient_dashboard.html`, patients `0017c9d8` and
  `6959e408`; temp DB assessment of `0017c9d8` (16 Nov 2026).
