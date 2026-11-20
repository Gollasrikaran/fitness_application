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
