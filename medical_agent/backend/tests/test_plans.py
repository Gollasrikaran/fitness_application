"""Plans drafted by fixed rules (no LLM) that only reach the patient once a
doctor approves them."""


def pending(client, doctor):
    rows = client.get("/doctor/proposals", headers=doctor).json()
    assert len(rows) == 1, rows
    return client.get(f"/doctor/proposals/{rows[0]['id']}", headers=doctor).json()


def approve(client, doctor, proposal_id, **edits):
    r = client.post(f"/doctor/proposals/{proposal_id}/approve", headers=doctor, json=edits)
    assert r.status_code == 201, r.text
    return r.json()


def plan_types(plan):
    return [e["activity_type"] for e in plan["exercises"]]


def test_new_patient_waits_for_doctor_to_approve_starter_plan(client, patient, doctor):
    h = patient()  # beginner, chronic back pain
    assert client.get("/plans", headers=h).json() == []
    assert client.get("/plans/pending", headers=h).json()["kind"] == "starter"
    assert "exercises" not in client.get("/plans/pending", headers=h).json()  # nothing to follow yet

    draft = pending(client, doctor)
    assert draft["source"] == "rules"
    # Most useful first, 4 for a beginner, "modify" exercises (dead bug) left out.
    assert plan_types(draft) == ["glute_bridge", "walk", "neck_isometric", "shoulder_circles"]
    assert draft["exercises"][0] == {"activity_type": "glute_bridge", "name": "Glute Bridge", "unit": "count",
                                     "sets": 2, "amount": 5, "notes": ""}

    approve(client, doctor, draft["id"])
    plans = client.get("/plans", headers=h).json()
    assert len(plans) == 1 and plan_types(plans[0]) == plan_types(draft)
    assert client.get("/plans/pending", headers=h).json() is None
    assert client.get("/chat", headers=h).json()[-1]["role"] == "doctor"
    assert client.get("/agent/context", headers=h).json()["doctor_plan"]["id"] == plans[0]["id"]


def test_starter_prefers_safe_over_modify(client, patient, doctor):
    patient(conditions=["arthritis_knee", "depression"])  # running ranks high for depression, "modify" for knees
    assert plan_types(pending(client, doctor)) == ["walk", "glute_bridge", "dead_bug", "shoulder_circles"]


def test_experience_sets_the_plan_size(client, patient, doctor):
    h = patient()
    client.put("/profile", headers=h, json={"age": 34, "sex": "female", "experience": "active",
                                            "conditions": ["chronic_back_pain"]})
    assert len(pending(client, doctor)["exercises"]) == 7  # the redraft replaced the beginner one


def test_refer_condition_gets_no_rule_draft(client, patient, doctor):
    patient(conditions=["heart_condition"])
    draft = pending(client, doctor)
    assert draft["source"] == "doctor" and draft["exercises"] == [] and "Heart problem" in draft["reason"]

    r = client.post(f"/doctor/proposals/{draft['id']}/approve", headers=doctor, json={})
    assert r.status_code == 422  # the doctor has to write this one
    approve(client, doctor, draft["id"], instructions="Walk on flat ground only.",
            exercises=[{"activity_type": "walk", "sets": 1, "amount": 0.5}])


def test_profile_resave_keeps_or_redrafts_starter(client, patient, doctor):
    h = patient()
    first = pending(client, doctor)["id"]
    same = {"age": 34, "sex": "female", "height_cm": 162, "weight_kg": 60, "conditions": ["chronic_back_pain"]}
    client.put("/profile", headers=h, json=same)
    assert pending(client, doctor)["id"] == first
    client.put("/profile", headers=h, json={"age": 34, "sex": "female", "conditions": ["carpal_tunnel"]})
    assert pending(client, doctor)["id"] != first
    statuses = {p["status"] for p in client.get("/doctor/proposals?status=all", headers=doctor).json()}
    assert statuses == {"pending", "superseded"}


def test_patient_with_a_plan_gets_no_new_starter(client, patient, doctor):
    h = patient()
    approve(client, doctor, pending(client, doctor)["id"])
    client.put("/profile", headers=h, json={"age": 35, "sex": "female", "conditions": ["chronic_back_pain"]})
    assert client.get("/doctor/proposals", headers=doctor).json() == []


def test_too_hard_drops_named_exercise_one_step(client, patient, doctor):
    h = patient()
    approve(client, doctor, pending(client, doctor)["id"])
    r = client.post("/plans/too-hard", headers=h, json={"activity_types": ["glute_bridge"],
                                                         "note": "bridges hurt my back"})
    assert r.status_code == 201 and r.json()["status"] == "pending_review"

    draft = pending(client, doctor)
    assert draft["kind"] == "easier" and draft["patient_note"] == "bridges hurt my back"
    assert draft["based_on_plan"]["exercises"][0]["amount"] == 5
    assert draft["changes"] == [{"activity_type": "glute_bridge", "name": "Glute Bridge",
                                 "from": {"sets": 2, "amount": 5}, "to": {"sets": 2, "amount": 3},
                                 "note": "5 -> 3 count per set"}]
    assert [e["amount"] for e in draft["exercises"]] == [3, 1.0, 5, 5]  # the others are untouched

    # The old plan stays in force until the doctor approves the new one.
    assert client.get("/plans", headers=h).json()[0]["exercises"][0]["amount"] == 5
    assert client.post("/plans/too-hard", headers=h, json={}).status_code == 409  # one draft at a time
    approve(client, doctor, draft["id"])
    assert client.get("/plans", headers=h).json()[0]["exercises"][0]["amount"] == 3


def test_too_hard_on_everything(client, patient, doctor):
    h = patient()
    approve(client, doctor, pending(client, doctor)["id"],
            exercises=[{"activity_type": "walk", "sets": 1, "amount": 1},
                       {"activity_type": "neck_isometric", "sets": 2, "amount": 5},
                       {"activity_type": "ankle_circles", "sets": 1, "amount": 2}])
    client.post("/plans/too-hard", headers=h, json={})
    notes = [c["note"] for c in pending(client, doctor)["changes"]]
    assert notes == ["1 -> 0.8 km per set",                          # amount drops a step
                     "2 -> 1 sets",                                  # amount already at one step: lose a set
                     "Already at the lowest dose; needs the doctor's decision"]


def test_too_hard_with_high_pain_goes_to_doctor_case(client, patient, doctor):
    h = patient()
    approve(client, doctor, pending(client, doctor)["id"])
    out = client.post("/plans/too-hard", headers=h, json={"pain_level": 8}).json()
    assert out["status"] == "doctor_case" and out["case"]["urgency"] == "priority"
    assert client.get("/doctor/proposals", headers=doctor).json() == []


def test_too_hard_needs_a_plan_and_its_exercises(client, patient, doctor):
    h = patient()
    assert client.post("/plans/too-hard", headers=h, json={}).status_code == 409
    approve(client, doctor, pending(client, doctor)["id"])
    assert client.post("/plans/too-hard", headers=h, json={"activity_types": ["running"]}).status_code == 422


def test_rejected_draft_cannot_be_approved(client, patient, doctor):
    h = patient()
    draft_id = pending(client, doctor)["id"]
    r = client.post(f"/doctor/proposals/{draft_id}/reject", headers=doctor, json={"note": "Wants a scan first"})
    assert r.json()["status"] == "rejected"
    assert client.post(f"/doctor/proposals/{draft_id}/approve", headers=doctor, json={}).status_code == 409
    assert client.get("/plans", headers=h).json() == []


def test_doctor_plan_on_a_case_replaces_pending_draft(client, patient, doctor, llm):
    h = patient()
    llm.response.update(decision="doctor", doctor_summary="Needs review.")
    case_id = client.post("/chat", headers=h, json={"message": "it hurts a lot"}).json()["case"]["id"]
    client.post(f"/doctor/cases/{case_id}/plan", headers=doctor, json={"instructions": "Rest for now."})
    assert client.get("/doctor/proposals", headers=doctor).json() == []


def test_only_doctors_review_drafts(client, patient):
    h = patient()
    assert client.get("/doctor/proposals", headers=h).status_code == 403


def test_older_patient_starts_one_step_lower(client, patient, doctor):
    h = patient()
    client.put("/profile", headers=h, json={"age": 68, "sex": "male", "conditions": ["chronic_back_pain"]})
    draft = pending(client, doctor)
    # glute bridge 5 -> 3, walk 1 -> 0.8; the neck hold is already at one step (5 s) and stays.
    assert [(e["activity_type"], e["amount"]) for e in draft["exercises"]] == [
        ("glute_bridge", 3), ("walk", 0.8), ("neck_isometric", 5), ("shoulder_circles", 3)]
    assert "age 68 >= 60 (provisional rule)" in draft["reason"]


def test_high_bmi_leaves_out_running(client, patient, doctor):
    h = patient()
    client.put("/profile", headers=h, json={"age": 34, "sex": "male", "height_cm": 160, "weight_kg": 90,
                                            "experience": "active", "conditions": []})
    draft = pending(client, doctor)
    assert "running" not in plan_types(draft) and len(draft["exercises"]) == 7
    assert "Running left out: BMI 35.2 >= 30" in draft["reason"]


def test_new_condition_redrafts_the_plan(client, patient, doctor):
    h = patient()
    approve(client, doctor, pending(client, doctor)["id"],
            exercises=[{"activity_type": "walk", "sets": 1, "amount": 2},
                       {"activity_type": "hamstring_stretch", "sets": 2, "amount": 15}])
    client.put("/profile", headers=h, json={"age": 34, "sex": "female",
                                            "conditions": ["chronic_back_pain", "herniated_disk"]})
    draft = pending(client, doctor)
    assert draft["kind"] == "update" and "added Slip disc" in draft["reason"]
    # Hamstring stretch is "avoid" for a slip disc: out, and the most useful safe exercise takes its place.
    assert [(e["activity_type"], e["amount"]) for e in draft["exercises"]] == [("walk", 2), ("glute_bridge", 5)]
    assert [c["note"] for c in draft["changes"]] == ["Removed: not safe with Slip disc",
                                                     "Added in place of a removed exercise"]
    assert plan_types(client.get("/plans", headers=h).json()[0]) == ["walk", "hamstring_stretch"]  # until approved
    approve(client, doctor, draft["id"])
    assert plan_types(client.get("/plans", headers=h).json()[0]) == ["walk", "glute_bridge"]


def test_condition_change_that_affects_nothing_needs_no_draft(client, patient, doctor):
    h = patient(conditions=["chronic_back_pain", "anxiety"])
    approve(client, doctor, pending(client, doctor)["id"])
    client.put("/profile", headers=h, json={"age": 34, "sex": "female", "conditions": ["chronic_back_pain"]})
    assert client.get("/doctor/proposals", headers=doctor).json() == []


def test_new_refer_condition_hands_the_plan_to_the_doctor(client, patient, doctor):
    h = patient()
    approve(client, doctor, pending(client, doctor)["id"])
    client.put("/profile", headers=h, json={"age": 34, "sex": "female",
                                            "conditions": ["chronic_back_pain", "heart_condition"]})
    draft = pending(client, doctor)
    assert (draft["kind"], draft["source"], draft["exercises"]) == ("update", "doctor", [])
    assert "Heart problem" in draft["reason"]
