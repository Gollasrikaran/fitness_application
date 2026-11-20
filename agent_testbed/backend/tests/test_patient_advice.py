"""Fix 02 (2026-11-20): the patient's instructions. The AI writes only the
opening; every condition's advice (data/conditions.csv, patient_advice),
the effort line and the warning signs are added by code, so two patients
with the same condition get the same safety lines."""
from agent.draft import EFFORT, RULES_OPENING, WARNING, build_draft, patient_profile
from store.models import Condition
from tests.test_draft import PATIENT, ai_down, ai_picking, assessment


def instructions(db, codes, opening="Start gently.", ask=None):
    return build_draft(db, "p1", assessment(codes), PATIENT, ask_ai=ask or ai_picking("walk", instructions=opening)
                       ).instructions


def test_two_diabetes_patients_get_the_same_safety_lines(db):
    a = instructions(db, ["diabetes_controlled"], "Start gently.").splitlines()
    b = instructions(db, ["diabetes_controlled"], "Build up over the weeks. A regular time helps.").splitlines()
    assert a[0] != b[0] and a[1:] == b[1:]
    assert any("something sweet" in line and "feet" in line for line in a)


def test_every_supported_condition_with_its_own_risks_has_advice(db):
    for code in ("diabetes_controlled", "bp_controlled", "asthma_controlled", "skin_fungal", "skin_dermatitis",
                 "arthritis_knee", "chronic_back_pain", "hand_pain", "hypothyroid", "obesity"):
        assert db.get(Condition, code).patient_advice, code


def test_asthma_says_carry_your_inhaler(db):
    assert "Carry your inhaler." in instructions(db, ["asthma_controlled"])


def test_the_broken_skin_line_is_always_there_for_a_skin_problem(db):
    for code in ("skin_fungal", "skin_dermatitis"):
        assert "broken or oozing" in instructions(db, [code]), code


def test_the_warning_signs_name_the_real_signs_and_come_last(db):
    lines = instructions(db, ["none"]).splitlines()
    assert lines[-1] == WARNING
    assert "puffing and mild muscle ache are normal" in WARNING and "doesn't settle with rest" in WARNING


def test_the_effort_line_comes_with_walking(db):
    assert EFFORT in instructions(db, ["none"])


def test_a_sentence_two_conditions_share_is_written_once(db):
    text = instructions(db, ["arthritis_knee", "arthritis_hip"])
    assert text.count("Some pain during exercise is fine if it settles by the next day") == 1


def test_no_hard_effort_warning_for_diabetes_or_bp(db):
    """I2: "avoid sudden intense exertion" stays a note for the doctor, not patient text."""
    text = instructions(db, ["diabetes_controlled", "bp_controlled"]).lower()
    assert "intense" not in text and "gentle activity" not in text


def test_a_rules_draft_gets_the_same_advice_and_no_text_for_the_doctor(db):
    p = build_draft(db, "p1", assessment(["asthma_controlled"]), PATIENT, ask_ai=ai_down)
    assert p.source == "rules"
    assert p.instructions.startswith(RULES_OPENING) and "Carry your inhaler." in p.instructions
    assert "safety rules" not in p.instructions


def test_the_draft_ai_reads_the_doctors_own_note():
    ctx = {"patient": {"age": 48, "sex": "F"}, "body": {"bmi": None},
           "medicines": {"from": "2026-09-09", "patient_instructions": "Use a moisturiser after bathing."}}
    assert patient_profile(ctx)["doctor_instructions"] == {"date": "2026-09-09",
                                                            "text": "Use a moisturiser after bathing."}
    assert patient_profile({**ctx, "medicines": {}})["doctor_instructions"] is None


def test_bmi_30_is_called_obesity_not_overweight(db):
    """Fix 06 (2026-11-20): the code is added at BMI 30+ (or "obese" in a diagnosis)."""
    assert db.get(Condition, "obesity").display_name == "Obesity"


# ── "Ask before approving" (fix 11, 2026-11-20) ─────────────────────────────

def asks(db, codes, age, sex, concerns=()):
    a = {**assessment(codes), "concerns": list(concerns)}
    return build_draft(db, "p1", a, {"age": age, "sex": sex, "bmi": 24.0}, ask_ai=ai_picking("walk")).ask_first


def test_everyone_gets_the_basic_questions(db):
    q = asks(db, ["none"], 40, "MALE")
    assert "Chest pain, breathlessness or dizziness when active?" in q and "Pain in the legs when walking?" in q
    assert "Do they smoke?" in q
    assert not any("falls" in x or "Pregnant" in x for x in q)


def test_a_woman_of_33_is_asked_about_pregnancy(db):
    """03cf014c (33 F, diabetes): pregnancy wasn't asked."""
    q = asks(db, ["diabetes_controlled", "obesity"], 33, "FEMALE")
    assert "Pregnant, or planning a pregnancy?" in q
    assert any("Feet and eyes" in x for x in q)


def test_at_66_falls_and_the_floor_are_asked(db):
    """30ca6dbf (66): no question on falls."""
    q = asks(db, ["asthma_controlled"], 66, "MALE")
    assert "Any falls in the last year?" in q and any("floor" in x for x in q)
    assert any("reliever inhaler" in x for x in q)


def test_two_diabetes_patients_get_the_same_questions(db):
    assert asks(db, ["diabetes_controlled"], 48, "FEMALE") == asks(db, ["diabetes_controlled"], 45, "FEMALE")


def test_the_rules_own_asks_are_added(db):
    leg = ('Leg or muscle pain (ask: pain on walking?) in the complaint on 2026-07-14: "Muscles pain in legs". '
           "Not a stop on its own: please ask about it before approving.")
    q = asks(db, ["bp_controlled"], 57, "MALE", [leg, "Clinic flag: 2 missed follow-ups"])
    assert f"From the record: {leg}" in q and not any("missed follow-ups" in x for x in q)
    assert "Any home BP readings?" in q


def test_a_doctor_must_write_draft_has_the_questions_too(db):
    a = {**assessment(["high_bp"], "severe", ["BP not under control"]), "concerns": []}
    p = build_draft(db, "p1", a, {"age": 70, "sex": "F"}, ask_ai=ai_picking())
    assert p.source == "doctor" and "Any falls in the last year?" in p.ask_first



def test_the_obesity_advice_doesnt_repeat_the_opening(db):
    """Test run 2026-11-20: "Start gently and build up" twice (the AI's opening and the obesity advice)."""
    assert "start gently" not in db.get(Condition, "obesity").patient_advice.lower()


# ── A thin or old record: a provisional draft (fix 12, 2026-11-20) ──────────

from datetime import date as _date

from agent.draft import provisional_line


def test_one_visit_is_provisional():
    """30ca6dbf: one visit on 26 Sep, draft on 20 Nov."""
    line = provisional_line({"first": "2026-09-26", "last": "2026-09-26", "dates": 1}, _date(2026, 11, 20), 30)
    assert line == ("Provisional draft: based on 1 visit (2026-09-26), the latest 55 days ago. "
                    "Please check the questions below before approving.")


def test_an_old_latest_visit_is_provisional():
    """6959e408: 15 visit dates, the latest on 10 Oct (41 days)."""
    line = provisional_line({"first": "2026-05-18", "last": "2026-10-10", "dates": 15}, _date(2026, 11, 20), 30)
    assert line.startswith("Provisional draft: based on 15 visits (2026-05-18 to 2026-10-10), the latest 41 days ago.")


def test_a_recent_record_is_not_provisional():
    assert provisional_line({"first": "2026-09-01", "last": "2026-11-10", "dates": 3}, _date(2026, 11, 20), 30) is None
    assert provisional_line(None, _date(2026, 11, 20), 30) is None


def test_a_provisional_draft_is_still_made_and_says_so_first(db):
    patient = {**PATIENT, "record": {"first": "2026-09-26", "last": "2026-09-26", "dates": 1}}
    p = build_draft(db, "p1", assessment(["asthma_controlled"]), patient, ask_ai=ai_picking("walk"),
                    today=_date(2026, 11, 20))
    assert p.source == "ai" and p.exercises
    assert p.reason.startswith("Provisional draft:") and p.ask_first[0].startswith("Provisional draft:")


def test_the_only_visit_for_a_cold_is_a_concern():
    from agent.routing import _short_illness_concerns
    ctx = {"visits": [{"date": "2026-09-26", "complaint": "Astama patient cough stikness cold  throat pain"}]}
    assert _short_illness_concerns(ctx) == ['The only visit (2026-09-26) was for a short illness: "Astama patient '
                                            'cough stikness cold  throat pain". Please check it has passed.']
    assert _short_illness_concerns({"visits": [{"date": "2026-10-06", "complaint": "skin Pigmertation"}]}) == []
    two = {"visits": [{"date": "2026-09-26", "complaint": "cough"}, {"date": "2026-08-01", "complaint": "knee pain"}]}
    assert _short_illness_concerns(two) == []
