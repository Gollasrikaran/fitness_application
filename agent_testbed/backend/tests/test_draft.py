"""Plan drafting (agent.draft): whatever the AI returns, no saved draft ever
holds an "avoid" exercise or a dose above the maximum."""
import random
from itertools import combinations

from sqlalchemy import select

from agent.draft import AIDraft, AIPick, build_draft
from store import plans
from store.models import Condition, Exercise, Plan, SafetyRule

PATIENT = {"age": 45, "sex": "F", "bmi": 24.0}


def assessment(codes, severity="moderate", reasons=()):
    return {"id": "assessment-1", "codes": codes, "severity": severity, "severe_reasons": list(reasons),
            "problem": "knee pain on walking", "body_area": "knee", "concerns": [],
            "conditions": [{"code": c, "name": c} for c in codes]}


def ai_picking(*kinds, instructions="Go slowly. Stop and phone your doctor if it hurts."):
    def ask(_assessment, _patient, _allowed):
        return AIDraft(exercises=[AIPick(activity_type=k, why="helps") for k in kinds],
                       instructions=instructions, reason="Gentle start.")
    return ask


def ai_down(*_):
    raise TimeoutError("no answer")


def ai_must_not_run(*_):
    raise AssertionError("the AI must not be asked for a severe case")


def safe_pick(db, code, n=3):
    allowed, _ = plans.candidates(db, [code], PATIENT["age"], PATIENT["bmi"])
    return [e["activity_type"] for e in allowed[:n]]


def an_avoid(db):
    r = db.scalars(select(SafetyRule).where(SafetyRule.verdict == "avoid").order_by(SafetyRule.id)).first()
    return r.condition_code, r.activity_type


def test_severe_gets_no_ai_draft(db):
    a = assessment(["arthritis_knee"], "severe", ["Chest pain in the complaint on 2026-10-01"])
    p = build_draft(db, "p1", a, PATIENT, ask_ai=ai_must_not_run)
    assert (p.source, p.exercises, p.assessment_id) == ("doctor", [], "assessment-1")
    assert "Chest pain" in p.reason


def test_refer_code_gets_no_draft_even_if_not_marked_severe(db):
    p = build_draft(db, "p1", assessment(["high_bp"]), PATIENT, ask_ai=ai_must_not_run)
    assert (p.source, p.exercises) == ("doctor", [])


def slot_options(db, codes, age=PATIENT["age"], bmi=PATIENT["bmi"], readings=None):
    allowed, _ = plans.candidates(db, codes, age, bmi, readings)
    return {name: [e["activity_type"] for e in options] for name, options in plans.plan_slots(allowed)}


def test_good_ai_draft_is_kept_at_the_rules_doses(db):
    """The AI takes a second option in one slot; the plan keeps the slot order."""
    slots = slot_options(db, ["arthritis_knee"])
    leg = slots["leg strength"][1]  # not the best fit: the AI's own choice
    p = build_draft(db, "p1", assessment(["arthritis_knee"]), PATIENT,
                    ask_ai=ai_picking(slots["breathing"][0], leg, slots["upper-body strength"][0], slots["balance"][0]))
    assert p.source == "ai"
    assert [e["activity_type"] for e in p.exercises] == ["walk", leg, slots["upper-body strength"][0],
                                                         slots["balance"][0], slots["breathing"][0]]
    for e in p.exercises:
        ex = db.get(Exercise, e["activity_type"])
        assert (e["sets"], e["amount"]) == (ex.default_sets, ex.default_amount)
    assert p.kind == "starter" and p.status == "pending" and p.instructions


def test_ai_picking_an_avoid_exercise_falls_back_to_rules(db):
    code, kind = an_avoid(db)
    p = build_draft(db, "p1", assessment([code]), PATIENT, ask_ai=ai_picking(*safe_pick(db, code, 2), kind))
    assert p.source == "rules"
    assert kind not in {e["activity_type"] for e in p.exercises}
    assert "AI draft not used" in p.reason


def test_ai_picking_an_unknown_exercise_falls_back_to_rules(db):
    p = build_draft(db, "p1", assessment(["chronic_back_pain"]), PATIENT, ask_ai=ai_picking("walk", "burpees"))
    assert p.source == "rules" and plans.violations(db, p.exercises, ["chronic_back_pain"]) == []


def test_ai_off_the_options_or_two_in_one_slot_or_no_instructions_falls_back(db):
    six = [e.activity_type for e in db.scalars(select(Exercise).order_by(Exercise.priority_order))][:6]
    two_legs = slot_options(db, ["none"])["leg strength"][:2]
    for ask in (ai_picking(*six), ai_picking(*two_legs), ai_picking("walk", instructions=" "), ai_picking()):
        p = build_draft(db, "p1", assessment(["none"]), PATIENT, ask_ai=ask)
        assert p.source == "rules", ask


def test_ai_picking_an_allowed_exercise_that_is_no_slot_option_falls_back(db):
    """6959e408 (2026-11-16) got Chin Tuck with no neck problem: it is allowed,
    but not one of the best few of any slot, so the AI can't pick it now."""
    slots = slot_options(db, ["bp_controlled", "obesity"], 57, 31.2)
    assert "chin_tuck" not in {k for options in slots.values() for k in options}
    p = build_draft(db, "p1", assessment(["bp_controlled", "obesity"]), {"age": 57, "sex": "M", "bmi": 31.2},
                    ask_ai=ai_picking("chin_tuck", "slow_breathing"))
    assert p.source == "rules" and "not one of the options" in p.reason


def test_ai_down_falls_back_to_rules(db):
    p = build_draft(db, "p1", assessment(["chronic_back_pain"]), PATIENT, ask_ai=ai_down)
    assert p.source == "rules" and p.exercises and "unavailable" in p.reason


def test_new_draft_replaces_the_pending_one(db):
    first = build_draft(db, "p1", assessment(["none"]), PATIENT, ask_ai=ai_down)
    second = build_draft(db, "p1", assessment(["none"]), PATIENT, ask_ai=ai_down)
    assert first.status == "superseded" and second.status == "pending"
    assert plans.pending_proposal(db, "p1").id == second.id


def test_patient_with_a_plan_gets_an_update_with_changes(db):
    old = Plan(patient_id="p1", doctor_id="d1", instructions="old",
               exercises=[{"activity_type": "running", "name": "Running", "unit": "km", "sets": 1, "amount": 1.0,
                           "notes": ""}], conditions=["none"])
    db.add(old)
    db.flush()
    p = build_draft(db, "p1", assessment(["arthritis_knee"]), PATIENT, ask_ai=ai_picking("walk", "glute_bridge"))
    assert (p.kind, p.based_on_plan_id) == ("update", old.id)
    notes = {(c["activity_type"], c["note"]) for c in p.changes}
    assert ("running", "Removed") in notes and ("walk", "Added") in notes


def test_no_draft_ever_breaks_the_rules(db):
    """Random AI answers (any exercise, junk, duplicates, too many) for random
    condition sets and patients: every saved draft passes the rules."""
    rng = random.Random(5)
    codes = list(db.scalars(select(Condition.code)))
    kinds = list(db.scalars(select(Exercise.activity_type))) + ["burpees", ""]
    avoid = {(r.condition_code, r.activity_type)
             for r in db.scalars(select(SafetyRule).where(SafetyRule.verdict == "avoid"))}
    maxima = {e.activity_type: e for e in db.scalars(select(Exercise))}
    combos = [[c] for c in codes] + [list(p) for p in combinations(codes, 2)]
    for i in range(600):
        combo = rng.choice(combos)
        patient = {"age": rng.choice([None, 25, 59, 60, 80]), "sex": "M", "bmi": rng.choice([None, 21.0, 30.0, 38.5])}
        ask = rng.choice([ai_down, ai_picking(*rng.sample(kinds, rng.randint(0, 7)))])
        p = build_draft(db, f"p{i}", assessment(combo, rng.choice(["mild", "moderate"])), patient, ask_ai=ask)
        assert plans.violations(db, p.exercises, combo) == [] or p.exercises == []
        for e in p.exercises:
            assert all((c, e["activity_type"]) not in avoid for c in combo)
            assert e["sets"] <= maxima[e["activity_type"]].max_sets
            assert e["amount"] <= maxima[e["activity_type"]].max_amount
        if any(db.get(Condition, c).bucket == "refer" for c in combo):
            assert p.source == "doctor" and p.exercises == []


# ── Walking leads every draft (research/*.md: walking is the core) ──────────

def test_walking_leads_an_ai_draft_even_when_the_ai_leaves_it_out(db):
    # The 2026-11-03 case: the AI swapped walking for marching on the spot.
    p = build_draft(db, "p1", assessment(["bp_controlled"]), PATIENT,
                    ask_ai=ai_picking("slow_breathing", "march_in_place", "sit_to_stand"))
    kinds = [e["activity_type"] for e in p.exercises]
    assert p.source == "ai" and kinds[0] == "walk" and "march_in_place" not in kinds
    assert p.exercises[0]["why"].startswith("BP under control: walking-type exercise lowers resting BP")


def test_each_exercise_carries_its_own_why_not_the_reason(db):
    """2026-11-17: the per-exercise lines moved from "Why this draft" to the
    exercise itself; the reason keeps the AI's summary and the rule lines."""
    p = build_draft(db, "p1", assessment(["bp_controlled"]), PATIENT,
                    ask_ai=ai_picking("sit_to_stand", "walk", "slow_breathing"))
    assert p.source == "ai" and all(e["why"] for e in p.exercises)
    assert not any(line.startswith("- ") for line in p.reason.splitlines())
    assert "Doses are the reviewed starting doses" in p.reason


def test_walking_is_not_repeated_when_the_ai_already_picked_it(db):
    p = build_draft(db, "p1", assessment(["bp_controlled"]), PATIENT,
                    ask_ai=ai_picking("sit_to_stand", "walk", "slow_breathing"))
    assert [e["activity_type"] for e in p.exercises].count("walk") == 1
    assert p.exercises[0]["why"] == "helps"  # the AI's own line, no numbers (plan C)


# ── A balanced plan (2026-11-16; PENDING_CHANGES.md 1, options B + D) ────────

def test_a_slot_the_ai_leaves_out_gets_its_best_fit(db):
    slots = slot_options(db, ["bp_controlled"])
    p = build_draft(db, "p1", assessment(["bp_controlled"]), PATIENT, ask_ai=ai_picking("slow_breathing"))
    assert p.source == "ai"
    assert [e["activity_type"] for e in p.exercises] == ["walk", *(slots[s][0] for s in
                                                                   ("leg strength", "upper-body strength", "balance")),
                                                         "slow_breathing"]
    assert "lowers resting BP" in p.exercises[1]["why"]  # the slot's best fit, with our research line


def test_ai_writing_names_instead_of_ids_keeps_the_ai_draft(db):
    """6959e408 (2026-11-16): the AI returned "walking" (the name, and the
    core it was told to leave out), so the whole AI draft was dropped."""
    p = build_draft(db, "p1", assessment(["bp_controlled", "obesity"]), {"age": 57, "sex": "M", "bmi": 31.2},
                    ask_ai=ai_picking("walking", "Sit to Stand", "wall-pushup", "slow_breathing"))
    assert p.source == "ai", p.reason
    assert [e["activity_type"] for e in p.exercises][:3] == ["walk", "sit_to_stand", "wall_pushup"]
    assert p.exercises[0]["why"] == "helps"


def test_6959e408_gets_a_balanced_plan(db):
    """BP + overweight, 57, BMI 31.2, BP 133/87: today's rules draft. Sit to
    Stand is "modify" for overweight (a sturdy chair) but keeps its rank (D)."""
    exercises, _ = plans.starter_exercises(db, ["bp_controlled", "obesity"], 57, 31.2,
                                           readings={"bp": {"sys": 133, "dia": 87, "date": "2026-10-10"}})
    assert [e["activity_type"] for e in exercises] == ["walk", "sit_to_stand", "wall_pushup", "single_leg_stand",
                                                      "slow_breathing"]
    assert exercises[1]["notes"]  # the caution note goes along


def test_every_plan_is_walking_then_strength_balance_and_breathing_last(db):
    types = {e.activity_type: e.exercise_type for e in db.scalars(select(Exercise))}
    for code in ("none", "bp_controlled", "diabetes_controlled", "asthma_controlled", "arthritis_knee", "obesity"):
        exercises, _ = plans.starter_exercises(db, [code], 45, 24.0)
        kinds = [types[e["activity_type"]] for e in exercises]
        assert kinds == ["aerobic", "strength", "strength", "balance", "breathing"], (code, kinds)


def test_no_holding_exercise_in_a_draft_and_no_strength_at_bp_160(db):
    """At BP 160-179 only walking-type, balance, breathing and mobility are
    allowed: the strength slots stay empty and gentle movements fill the plan."""
    types = {e.activity_type: e.exercise_type for e in db.scalars(select(Exercise))}
    exercises, _ = plans.starter_exercises(db, ["bp_controlled"], 50, 24.0,
                                           readings={"bp": {"sys": 165, "dia": 100, "date": "2026-11-10"}})
    kinds = [types[e["activity_type"]] for e in exercises]
    assert kinds[0] == "aerobic" and kinds[-1] == "breathing" and len(kinds) == 5
    assert "strength" not in kinds and "isometric" not in kinds
    for code in ("none", "bp_controlled", "arthritis_knee"):
        allowed, _ = plans.candidates(db, [code], 45, 24.0)
        offered = {e["activity_type"] for _, options in plans.plan_slots(allowed) for e in options}
        assert not offered & {"wall_sit", "neck_isometric"}, code


def test_no_exercise_is_offered_in_two_slots(db):
    for code in ("none", "bp_controlled", "arthritis_knee", "asthma_controlled"):
        allowed, _ = plans.candidates(db, [code], 45, 24.0)
        offered = [e["activity_type"] for _, options in plans.plan_slots(allowed) for e in options]
        assert len(offered) == len(set(offered)), code


def test_the_rules_draft_starts_with_walking_too(db):
    for code in ("bp_controlled", "diabetes_controlled", "asthma_controlled", "none"):
        exercises, _ = plans.starter_exercises(db, [code], PATIENT["age"], PATIENT["bmi"])
        assert exercises[0]["activity_type"] == "walk", code
        assert not {"march_in_place", "seated_march"} & {e["activity_type"] for e in exercises}, code


def test_breathlessness_in_everyday_words_is_a_warning(db):
    """Any patient, any condition: these send the plan to a doctor (the
    2026-11-03 case said "breathing problem while walking")."""
    from agent.conditions import load_reference, rule_findings
    from store.models import WarningComplaint
    from store.seed import _rows
    ref = load_reference(db)
    ref.warnings = [WarningComplaint(phrase=r["phrase"].strip().lower(), label=r["label"])
                    for r in _rows("warning_complaints.csv")]
    for complaint in ("Frequent urination, breathing problem while walking", "SOB on exertion",
                      "short of breath climbing stairs", "difficulty breathing at night"):
        ctx = {"conditions": {"doctor_recorded": [], "long_term_conditions": [], "health_history": []},
               "body": {}, "visits": [{"date": plans.date.today().isoformat(), "complaint": complaint}]}
        assert {w["label"] for w in rule_findings(ctx, ref).warnings} == {"Breathlessness"}, complaint


# ── The "why" under each exercise (2026-11-17) ──────────────────────────────

def test_without_an_ai_line_and_evidence_the_rules_line_names_the_part_of_the_plan(db):
    slots = slot_options(db, ["pcos"])  # no research lines for PCOD
    p = build_draft(db, "p1", assessment(["pcos"]), PATIENT, ask_ai=ai_picking(slots["breathing"][0]))
    assert p.source == "ai"
    assert p.exercises[-1]["why"] == "helps"  # the AI's own line
    assert p.exercises[1]["why"] == "Leg strength: the best-ranked option for this part of the plan (chosen by the safety rules)."
    assert p.exercises[0]["why"].startswith("Main exercise of the plan")


def ai_with_whys(whys):
    def ask(_assessment, _patient, _allowed):
        return AIDraft(exercises=[AIPick(activity_type=k, why=w) for k, w in whys.items()],
                       instructions="Go slowly.", reason="Gentle start.")
    return ask


def test_the_ai_line_may_quote_only_numbers_from_the_evidence_or_the_patient(db):
    """Plan C (2026-11-17): the AI writes every why, with our research as its
    only source of health facts. A number it made up drops its line."""
    p = build_draft(db, "p1", assessment(["bp_controlled"]), {"age": 57, "sex": "M", "bmi": 31.2},
                    ask_ai=ai_with_whys({
                        "walk": "Walking lowers resting BP by about 4-7 mmHg, which suits his BP.",  # from the evidence
                        "sit_to_stand": "Leg strength lowers BP by 12 mmHg.",  # invented: dropped
                        "slow_breathing": "Calming breathing for a 57-year-old with BMI 31.2."}))  # his own numbers
    why = {e["activity_type"]: e["why"] for e in p.exercises}
    assert why["walk"] == "Walking lowers resting BP by about 4-7 mmHg, which suits his BP."
    assert why["sit_to_stand"].startswith("BP under control: strength exercise with movement")  # our line instead
    assert why["slow_breathing"] == "Calming breathing for a 57-year-old with BMI 31.2."


def test_evidence_lines_use_short_condition_names(db):
    allowed, _ = plans.candidates(db, ["skin_condition"], 40, 24)
    walk = next(e for e in allowed if e["activity_type"] == "walk")
    assert walk["benefits"] == ["Skin problem: allowed as usual; walk at a cool time of day to limit sweat and itch"]


def test_skin_advice_separates_eczema_and_fungal_infection(db):
    notes = db.get(Condition, "skin_condition").notes
    assert "dry well" in notes and "Eczema: put on your moisturiser" in notes and "keep the area dry" in notes


def test_the_ai_gets_the_conditions_advice(db):
    seen = {}

    def ask(assessment, patient, allowed):
        seen.update(patient)
        return ai_picking("walk")(assessment, patient, allowed)

    build_draft(db, "p1", assessment(["skin_condition"]), PATIENT, ask_ai=ask)
    assert "loose cotton" in seen["condition_notes"]["Skin problem (eczema, fungal infection)"]


def test_every_research_line_belongs_to_a_safety_rule(db):
    from store.seed import _rows
    lines = list(_rows("exercise_benefits.csv"))
    assert lines and all(r["benefit"].strip() and r["source"].strip() for r in lines)
    for r in lines:
        rule = db.scalars(select(SafetyRule).where(SafetyRule.condition_code == r["condition_code"],
                                                   SafetyRule.activity_type == r["activity_type"])).one()
        assert rule.benefit == r["benefit"].strip()


def test_part_names_from_the_ai_mean_that_parts_best_fit(db):
    """6959e408 (2026-11-17): the AI returned "leg strength", "upper-body
    strength", "breathing" instead of exercises, and the AI draft was lost."""
    slots = slot_options(db, ["bp_controlled", "obesity"], age=57, bmi=31.2)
    p = build_draft(db, "p1", assessment(["bp_controlled", "obesity"]), {"age": 57, "sex": "M", "bmi": 31.2},
                    ask_ai=ai_picking("walk", "leg strength", "upper-body strength", "balance", "breathing"))
    assert p.source == "ai", p.reason
    assert [e["activity_type"] for e in p.exercises] == ["walk", *(slots[s][0] for s in
                                                                   ("leg strength", "upper-body strength", "balance",
                                                                    "breathing"))]


def test_a_rules_draft_has_a_why_under_each_exercise_too(db):
    p = build_draft(db, "p1", assessment(["bp_controlled"]), PATIENT, ask_ai=ai_picking("no_such_exercise"))
    assert p.source == "rules"
    assert all(e["why"] for e in p.exercises)
    assert "lowers resting BP" in p.exercises[0]["why"]  # our research line (no AI line)


def test_the_draft_ai_never_sees_the_medicine_notes():
    """6959e408 (2026-11-18): the AI justified a balance exercise with cetirizine's
    drowsiness. Medicine notes are for the doctor only; the other concerns stay."""
    from agent.draft import patient_for_ai
    a = {"problem": "tinea and obesity", "body_area": "skin", "conditions": [{"code": "obesity", "name": "Overweight"}],
         "concerns": ["Weakness was the complaint on 2026-07-20.", "Medicine: TAB CITRIZINE: may cause drowsiness",
                      "medicine: Amlodipine: dizziness on standing", "Clinic flag: 2 missed follow-ups"]}
    seen = patient_for_ai(a, {"age": 57, "sex": "MALE", "bmi": 31.2})
    assert seen["concerns"] == ["Weakness was the complaint on 2026-07-20.", "Clinic flag: 2 missed follow-ups"]
    assert "citrizine" not in str(seen).lower() and "amlodipine" not in str(seen).lower()
    assert a["concerns"][1].startswith("Medicine:")  # the doctor's copy is untouched
