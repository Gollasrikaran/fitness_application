"""Doctor review (store.plans): the doctor has the final say. The grid only
warns; just input errors are refused."""
import pytest
from sqlalchemy import select

from store import plans
from store.models import Assessment, Exercise, PlanProposal, SafetyRule


def an_avoid(db):
    r = db.scalars(select(SafetyRule).where(SafetyRule.verdict == "avoid").order_by(SafetyRule.id)).first()
    return r.condition_code, r.activity_type


def item(kind, sets=2, amount=5, notes=""):
    return {"activity_type": kind, "sets": sets, "amount": amount, "notes": notes}


def test_doctor_can_approve_an_avoid_exercise_and_a_big_dose(db):
    code, kind = an_avoid(db)
    walk = db.get(Exercise, "walk")
    p = PlanProposal(patient_id="p1", kind="starter", source="ai", instructions="draft", exercises=[], reason="",
                     conditions=[code])
    db.add(p)
    db.flush()
    chosen = plans.doctor_exercises(db, [item(kind), item("walk", sets=walk.max_sets + 2, amount=walk.max_amount * 2)])
    plan = plans.approve(db, p, "d1", "Do these slowly.", chosen, None)
    assert [e["activity_type"] for e in plan.exercises] == [kind, "walk"]
    assert plan.exercises[1]["sets"] == walk.max_sets + 2
    assert p.status == "approved" and plans.latest_plan(db, "p1").id == plan.id


def test_doctor_edit_keeps_names_units_and_notes(db):
    out = plans.doctor_exercises(db, [item("walk", 1, 2.5, "  morning only ")])
    assert out == [{"activity_type": "walk", "name": "Walking", "unit": "km", "sets": 1, "amount": 2.5,
                    "notes": "morning only"}]


@pytest.mark.parametrize("bad", [
    [item("burpees")],
    [item("walk"), item("walk")],
    [item("walk", sets=0)],
    [item("walk", sets=1.5)],
    [item("walk", amount=0)],
    [item("walk", amount=-1)],
])
def test_only_input_errors_are_refused(db, bad):
    with pytest.raises(ValueError):
        plans.doctor_exercises(db, bad)


def test_doctor_may_approve_no_exercises(db):
    assert plans.doctor_exercises(db, []) == []


def test_warnings_for_avoid_unreviewed_and_over_max(db):
    code, kind = an_avoid(db)
    walk = db.get(Exercise, "walk")
    w = plans.doctor_warnings(db, [item(kind), item("walk", sets=walk.max_sets + 1)], [code])
    assert any("Marked avoid" in x for x in w[kind])
    assert any("above the usual maximum" in x for x in w["walk"])
    unreviewed = plans.doctor_warnings(db, [item("walk", 1, 1)], ["high_bp"])  # refer: no rules
    assert any("Not reviewed" in x for x in unreviewed["walk"])
    assert plans.doctor_warnings(db, [item("walk", 1, 1)], ["none"]) == {}


def test_catalog_marks_verdicts_for_the_patient(db):
    code, kind = an_avoid(db)
    by_type = {e["activity_type"]: e for e in plans.exercise_catalog(db, [code])}
    assert len(by_type) == 12 and by_type[kind]["verdict"] == "avoid"
    assert all(e["verdict"] == "unreviewed" for e in plans.exercise_catalog(db, ["high_bp"]))


def test_queue_holds_this_doctors_pending_drafts_oldest_first(db):
    for i, doctor in enumerate(("d1", "d2", "d1")):
        a = Assessment(id=f"a{i}", patient_id=f"p{i}", doctor_id=doctor, codes=["none"], severity="mild",
                       ai_status="ok")
        db.add(a)
        db.add(PlanProposal(patient_id=f"p{i}", assessment_id=a.id, kind="starter", source="ai", instructions="x",
                            exercises=[], reason="", conditions=["none"]))
        db.flush()
    queue = plans.review_queue(db, "d1")
    assert [q["patient_id"] for q in queue] == ["p0", "p2"]
    db.scalars(select(PlanProposal).where(PlanProposal.patient_id == "p0")).one().status = "approved"
    assert [q["patient_id"] for q in plans.review_queue(db, "d1")] == ["p2"]


def test_review_summary_counts_what_doctors_changed(db):
    def draft(source, exercises):
        p = PlanProposal(patient_id="p1", kind="starter", source=source, instructions="Daily.",
                         exercises=plans.doctor_exercises(db, exercises), reason="", conditions=[])
        db.add(p)
        db.flush()
        return p

    plans.approve(db, draft("ai", [item("walk", 1, 1)]), "d1", None, None, None)  # as drafted
    edited = draft("ai", [item("walk", 1, 1), item("glute_bridge", 2, 5)])
    plans.approve(db, edited, "d1", "Daily, slowly.",
                  plans.doctor_exercises(db, [item("walk", 1, 2), item("calf_stretch", 2, 10)]), None)
    plans.reject(draft("rules", [item("walk", 1, 1)]), "d2", "Patient can't walk far")
    plans.approve(db, draft("doctor", []), "d1", "Rest.", plans.doctor_exercises(db, [item("walk", 1, 1)]), None)
    draft("ai", [item("walk", 1, 1)])  # still waiting: not counted
    db.flush()

    out = plans.review_summary(db)
    assert out["by_source"]["ai"] == {"reviewed": 2, "approved_as_drafted": 1, "approved_with_edits": 1, "rejected": 0}
    assert out["by_source"]["rules"]["rejected"] == 1
    assert out["doctor_written_approved"] == 1
    assert [x["name"] for x in out["added"]] == ["Wall Calf Stretch"]
    assert [x["name"] for x in out["removed"]] == ["Glute Bridge"]
    assert out["dose_raised"] == 1 and out["dose_lowered"] == 0 and out["instructions_changed"] == 1
    assert out["rejections"] == [{"source": "rules", "note": "Patient can't walk far"}]
    assert plans.review_summary(db, "d2")["by_source"] == {"rules": {"reviewed": 1, "approved_as_drafted": 0,
                                                                     "approved_with_edits": 0, "rejected": 1}}
