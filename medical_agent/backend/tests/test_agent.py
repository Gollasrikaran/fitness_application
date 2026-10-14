"""The triage rules, end to end through the HTTP API, with the LLM faked."""
from datetime import date, timedelta

from tests.conftest import supabase_token


def chat(client, headers, text):
    r = client.post("/chat", headers=headers, json={"message": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_self_care_with_only_approved_exercises(client, patient, llm):
    h = patient()
    llm.response.update(suggested_exercises=["walk", "not_a_real_exercise", "glute_bridge"])
    out = chat(client, h, "my back is a bit stiff this morning")
    assert out["decision"] == "self_care"
    assert [e["activity_type"] for e in out["exercises"]] == ["walk", "glute_bridge"]
    assert out["case"] is None


def test_agent_sees_profile_progress_and_history(client, patient, llm):
    h = patient()
    client.post("/progress", headers=h, json={"activity_type": "walk", "sets": 1, "amount": 2, "pain_level": 3})
    chat(client, h, "first message")
    chat(client, h, "second message")
    sent = llm.calls[-1]
    context = sent[1]["content"]
    assert "Long-standing back pain" in context and '"active_days": 1' in context
    assert [m["content"] for m in sent if m["role"] == "user"] == ["first message", "second message"]


def test_emergency_skips_llm_and_opens_urgent_case(client, patient, doctor, llm):
    h = patient()
    out = chat(client, h, "mujhe seene mein dard ho raha hai")
    assert out["decision"] == "emergency" and "112" in out["reply"]
    assert llm.calls == []
    cases = client.get("/doctor/cases", headers=doctor).json()
    assert len(cases) == 1 and cases[0]["urgency"] == "emergency"


def test_refer_condition_forces_doctor_even_if_llm_says_self_care(client, patient, llm):
    h = patient(conditions=["heart_condition"])
    out = chat(client, h, "is it ok to go for a walk?")
    assert out["decision"] == "doctor"
    assert out["exercises"] == []          # refer conditions approve nothing
    assert "doctor" in out["reply"].lower()
    assert '"REQUIRED_DECISION": "doctor"' in llm.calls[0][1]["content"]


def test_high_stated_pain_forces_doctor(client, patient, llm):
    h = patient()
    llm.response.update(pain_score=8)
    assert chat(client, h, "pain is 8 out of 10 today")["decision"] == "doctor"


def test_rising_pain_trend_forces_doctor(client, patient, llm):
    h = patient()
    today = date.today()
    for days_ago, pain in [(10, 2), (9, 2), (2, 5), (1, 6)]:
        client.post("/progress", headers=h, json={"activity_type": "walk", "amount": 1, "pain_level": pain,
                                                  "logged_on": (today - timedelta(days=days_ago)).isoformat()})
    out = chat(client, h, "how am I doing?")
    assert out["decision"] == "doctor"
    assert "pain_rising" in client.get("/agent/context", headers=h).json()["progress"]["signals"][0]["code"]


def test_repeat_escalations_reuse_one_open_case(client, patient, doctor, llm):
    h = patient()
    llm.response.update(decision="doctor", urgency="routine", doctor_summary="Back pain for 3 weeks.")
    chat(client, h, "it has hurt for 3 weeks")
    chat(client, h, "still hurting")
    assert len(client.get("/doctor/cases", headers=doctor).json()) == 1


def test_llm_failure(client, patient, llm):
    llm.fail = True
    h = patient()
    r = client.post("/chat", headers=h, json={"message": "my back is stiff"})
    assert r.status_code == 503
    assert client.get("/chat", headers=h).json() == []  # nothing half-saved
    # ...but a forced referral still reaches the doctor without the LLM.
    h2 = patient(conditions=["recent_surgery"], email="p2@example.com")
    assert chat(client, h2, "can I exercise?")["decision"] == "doctor"


def test_reply_naming_unapproved_exercise_is_replaced_whole(client, patient, llm):
    h = patient(conditions=["heart_condition"])
    llm.response.update(decision="doctor", reply="Try Running for 10 minutes. A doctor will review this.")
    reply = chat(client, h, "what can I do?")["reply"]
    assert "running" not in reply.lower()
    assert reply.startswith("To be safe")  # a complete message, not a leftover fragment


def test_escalations_keep_earlier_summaries(client, patient, doctor, llm):
    h = patient()
    llm.response.update(decision="doctor", doctor_summary="Back pain 2 weeks with new leg tingling.")
    chat(client, h, "kamar mein dard 2 hafte se, pair mein jhunjhuni")
    case_id = chat(client, h, "mujhe seene mein dard ho raha hai")["case"]["id"]
    detail = client.get(f"/doctor/cases/{case_id}", headers=doctor).json()
    assert detail["urgency"] == "emergency"
    assert "leg tingling" in detail["summary"] and "Chest pain" in detail["summary"]


def test_memory_notes_persist(client, patient, llm):
    h = patient()
    llm.response.update(new_facts=["Pain started after lifting a suitcase"])
    chat(client, h, "it started after I lifted a suitcase")
    assert client.get("/agent/context", headers=h).json()["memory"] == ["Pain started after lifting a suitcase"]


def test_doctor_plan_reaches_patient_and_agent(client, patient, doctor, llm):
    h = patient()
    llm.response.update(decision="doctor", doctor_summary="Needs review.")
    case_id = chat(client, h, "it hurts a lot")["case"]["id"]

    detail = client.get(f"/doctor/cases/{case_id}", headers=doctor).json()
    assert detail["summary"] == "Needs review." and detail["patient_context"]["patient"]["age"] == 34

    r = client.post(f"/doctor/cases/{case_id}/plan", headers=doctor, json={
        "instructions": "Rest 3 days, then gentle walks.",
        "exercises": [{"activity_type": "walk", "sets": 1, "amount": 1, "notes": "flat ground"}]})
    assert r.status_code == 201
    assert client.get("/plans", headers=h).json()[0]["instructions"] == "Rest 3 days, then gentle walks."
    assert client.get("/chat", headers=h).json()[-1]["role"] == "doctor"
    assert client.get("/doctor/cases", headers=doctor).json() == []  # no longer open

    chat(client, h, "thanks")
    assert "Rest 3 days" in llm.calls[-1][1]["content"]


def test_roles_are_enforced(client, patient, doctor):
    h = patient()
    assert client.get("/doctor/cases", headers=h).status_code == 403
    assert client.post("/chat", headers=doctor, json={"message": "hi"}).status_code == 403
    assert client.get("/auth/me", headers=doctor).json()["role"] == "doctor"


def test_new_supabase_user_starts_as_patient(client):
    h = {"Authorization": f"Bearer {supabase_token('new@example.com')}"}
    me = client.get("/auth/me", headers=h).json()
    assert me["role"] == "patient" and me["name"] == "new" and me["has_profile"] is False


def test_bad_tokens_are_rejected(client):
    for token in [supabase_token("a@example.com", secret="wrong-secret"),
                  supabase_token("a@example.com", aud="anon"),
                  supabase_token("a@example.com", expires_in=-60),
                  "not-a-jwt"]:
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/auth/me").status_code == 401


def test_profile_rejects_free_text_conditions_and_minors(client, patient):
    h = patient()
    assert client.put("/profile", headers=h, json={"age": 30, "sex": "male",
                                                   "conditions": ["my knee hurts"]}).status_code == 422
    assert client.put("/profile", headers=h, json={"age": 16, "sex": "male"}).status_code == 422
