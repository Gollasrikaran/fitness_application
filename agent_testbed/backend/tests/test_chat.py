"""The doctor chat's inputs (agent/nodes.py → programme()): the conditions as
decided, not the raw bp_any; and the exercises of our programme the safety
rules allow, which the chat names before any no-equipment idea of its own."""
from datetime import date

import pytest

from agent.conditions import load_reference, rule_findings
from agent.nodes import plain, programme
from agent.prompts import DOCTOR_CHAT
from store.models import ConditionAlias, WarningComplaint

TODAY = date(2026, 10, 26)


@pytest.fixture
def ref(db):
    ref = load_reference(db)
    ref.aliases = [ConditionAlias(source="text", phrase="htn", code="bp_any")]
    ref.warnings = [WarningComplaint(phrase="chest pain", label="Chest pain")]
    return ref


def context(complaint=None, bmi=31.2, age=57):
    return {"patient": {"age": age, "sex": "M"},
            "visits": [{"date": "2026-10-10", "complaint": complaint, "diagnosis_provisional": "HTN",
                        "vitals": {"bp": "133/87"}}],
            "vital_flags": [], "alerts": {"emergencies": []},
            "conditions": {"doctor_recorded": [], "long_term_conditions": [], "health_history": []},
            "body": {"bmi": bmi, "measured_on": "2026-10-10"}}


def run(db, ref, ctx, assessment=None):
    return programme(db, ctx, ref, rule_findings(ctx, ref, TODAY), assessment, TODAY)


def test_bp_is_given_as_decided_not_as_the_raw_marker(db, ref):
    codes, conditions, _ = run(db, ref, context())
    assert "bp_controlled" in codes and "bp_any" not in codes
    assert "(bp_controlled)" in conditions and "bp_any" not in conditions
    assert "our rules alone" in conditions


def test_exercises_are_our_allowed_ones_by_type(db, ref):
    _, _, exercises = run(db, ref, context())
    assert "Walking-type:" in exercises and "Marching on the Spot" in exercises
    assert "Glute Bridge" not in exercises.split("Left out by the rules")[0]  # floor exercise, BMI 31.2
    assert "Left out by the rules" in exercises and "on the floor" in exercises


def test_a_doctor_must_write_the_plan_means_no_exercises(db, ref):
    _, conditions, exercises = run(db, ref, context(complaint="Chest pain since 2 days"))
    assert "A doctor must write this patient's plan" in conditions and "Chest pain" in conditions
    assert exercises.startswith("None: a doctor writes")


def test_the_latest_assessment_is_used_when_there_is_one(db, ref):
    assessment = {"codes": ["bp_controlled"], "severity": "moderate", "severe_reasons": [], "concerns": [],
                  "conditions": [{"code": "bp_controlled", "name": "BP under control",
                                  "evidence": ["visit 2026-10-10, diagnosis: \"HTN\""]}],
                  "readings": {}, "assessed_on": "2026-10-20T10:00"}
    codes, conditions, exercises = run(db, ref, context(), assessment)
    assert codes == ["bp_controlled"]
    assert "latest assessment (2026-10-20" in conditions and "BP under control" in conditions
    assert "Marching on the Spot" in exercises


def test_the_prompt_keeps_other_ideas_to_no_equipment():
    assert "[No equipment]" in DOCTOR_CHAT and "In our programme:" in DOCTOR_CHAT
    assert "never judge it from a reading" in DOCTOR_CHAT
    assert "AGENT_CONDITIONS" not in DOCTOR_CHAT


def test_the_reply_is_plain_text():
    reply = "**In our programme:**\n* **Marching on the Spot** (standing)\n## Safety\n- BP 133/87 on 2026-10-10"
    assert plain(reply) == "In our programme:\n- Marching on the Spot (standing)\nSafety\n- BP 133/87 on 2026-10-10"


def test_the_plan_status_only_when_asked():
    assert "only when the doctor asks about the plan" in DOCTOR_CHAT
    assert "Write plain text" in DOCTOR_CHAT


# ── "Provisional diagnosis" is not a finding (fix 07, 2026-11-20) ───────────

import pytest as _pytest

from agent.assess import _drop_known_missing, about_provisional
from agent.prompts import ASSESS


@_pytest.mark.parametrize("item", [
    "Asthma diagnosis at the 2026-09-26 visit is recorded as provisional",     # 30ca6dbf's concern
    "confirmed diagnosis (current diagnosis is provisional)",                  # 1123000d's missing item
    "The diagnosis of tinea is not yet confirmed", "Unconfirmed asthma",
])
def test_provisional_only_items_are_dropped(item):
    assert about_provisional(item)
    assert _drop_known_missing([item, "height (BMI cannot be calculated)"], {}) == ["height (BMI cannot be calculated)"]


@_pytest.mark.parametrize("item", [
    "Weakness reported at visit 2026-07-20 alongside the hypertension complaint; cause not recorded.",
    "Chest pain on 2026-10-01 with a provisional diagnosis of gastritis: check it has settled.",
])
def test_other_items_stay(item):
    assert not about_provisional(item)


def test_the_assessment_prompt_says_provisional_is_the_diagnosis():
    assert "Treat diagnosis_provisional as the diagnosis" in ASSESS
