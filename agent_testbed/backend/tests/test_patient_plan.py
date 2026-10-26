"""The patient's plan page (store.plans.patient_plan): only what a doctor
approved, with each exercise's details in plain words."""
from datetime import datetime, timedelta, timezone

from store import plans
from store.models import Exercise, Plan, PlanProposal


def item(kind, sets, amount, notes=""):
    return {"activity_type": kind, "sets": sets, "amount": amount, "notes": notes}


def approved(db, patient_id, exercises, instructions="Once a day.", when=None):
    p = PlanProposal(patient_id=patient_id, kind="starter", source="ai", instructions="draft", exercises=[],
                     reason="", conditions=["chronic_back_pain"])
    db.add(p)
    db.flush()
    plan = plans.approve(db, p, "d1", instructions, plans.doctor_exercises(db, exercises), None)
    if when:
        plan.created_at = when
    db.flush()
    return plan


def test_no_plan_until_a_doctor_approves(db):
    db.add(PlanProposal(patient_id="p1", kind="starter", source="ai", instructions="draft",
                        exercises=[item("walk", 1, 1)], reason="", conditions=[]))
    db.flush()
    assert plans.patient_plan(db, plans.latest_plan(db, "p1"), None) is None


def test_a_rejected_draft_is_never_shown(db):
    p = PlanProposal(patient_id="p1", kind="starter", source="ai", instructions="draft", exercises=[], reason="",
                     conditions=[])
    db.add(p)
    db.flush()
    plans.reject(p, "d1", "Not now")
    assert plans.latest_plan(db, "p1") is None


def test_the_newest_approved_plan_wins(db):
    now = datetime.now(timezone.utc)
    approved(db, "p1", [item("walk", 1, 1)], "old", when=now - timedelta(days=3))
    approved(db, "p1", [item("walk", 1, 2)], "new", when=now)
    out = plans.patient_plan(db, plans.latest_plan(db, "p1"), "Dr Rao")
    assert out["instructions"] == "new" and out["exercises"][0]["dose"] == "2 km"


def test_patient_sees_only_the_plan(db):
    plan = approved(db, "p1", [item("calf_stretch", 2, 10, "Gently")])
    out = plans.patient_plan(db, plan, "Dr Rao")
    assert set(out) == {"doctor_name", "given_on", "instructions", "exercises"}
    assert out["doctor_name"] == "Dr Rao" and out["instructions"] == "Once a day."
    assert set(out["exercises"][0]) == {"name", "dose", "rest_seconds", "steps", "notes"}


def test_exercise_details_come_from_the_exercise_table(db):
    ex = db.get(Exercise, "calf_stretch")
    ex.instructions = ["Face a wall.", "Lean in."]
    db.flush()
    out = plans.patient_plan(db, approved(db, "p1", [item("calf_stretch", 2, 10, "Gently")]), None)
    e = out["exercises"][0]
    assert e["name"] == ex.display_name
    assert e["dose"] == "2 sets × hold 10 seconds, each side"
    assert e["rest_seconds"] == ex.rest_seconds and e["steps"] == ["Face a wall.", "Lean in."]
    assert e["notes"] == "Gently"


def test_doses_in_plain_words(db):
    out = plans.patient_plan(db, approved(db, "p1", [item("glute_bridge", 2, 5), item("walk", 1, 1.5),
                                                     item("neck_isometric", 3, 20)]), None)
    assert [e["dose"] for e in out["exercises"]] == ["2 sets × 5 repetitions", "1.5 km", "3 sets × hold 20 seconds"]


def test_no_steps_and_no_rest_still_shows(db):
    e = plans.patient_plan(db, approved(db, "p1", [item("walk", 1, 1)]), None)["exercises"][0]
    assert e["steps"] == [] and e["rest_seconds"] is None  # one set: no rest between sets


def test_an_exercise_since_removed_from_the_table_still_shows(db):
    plan = approved(db, "p1", [item("glute_bridge", 2, 5)])
    plan.exercises = [{**plan.exercises[0], "activity_type": "gone"}]
    db.flush()
    e = plans.patient_plan(db, plan, None)["exercises"][0]
    assert e["name"] == "Glute Bridge" and e["dose"] == "2 sets × 5 repetitions" and e["steps"] == []
