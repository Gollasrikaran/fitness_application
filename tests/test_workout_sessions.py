"""Workout Player session tracking: start/finish, the self-healing
"only one active session" rule, and log_activity's workout_session_id tag.

Integration tests against the real local Postgres, same convention as the
rest of this suite — real HTTP calls through the Flask test client, not
mocked service calls.
"""
from app.platform.db import session_scope
from app.profile.models import WorkoutSession


def test_start_returns_planned_count_matching_input(make_user, client):
    user = make_user()
    r = client.post(
        "/v1/workout-sessions",
        json={"activity_types": ["walk", "glute_bridge", "dead_bug"]},
        headers=user["headers"],
    )
    assert r.status_code == 201
    body = r.get_json()
    assert body["planned_activity_count"] == 3
    assert body["id"]
    assert body["started_at"]


def test_starting_a_second_session_abandons_the_first(make_user, client):
    user = make_user()
    first = client.post(
        "/v1/workout-sessions", json={"activity_types": ["walk"]}, headers=user["headers"],
    ).get_json()
    client.post(
        "/v1/workout-sessions", json={"activity_types": ["walk"]}, headers=user["headers"],
    )
    # The first session is no longer active — finishing it now must fail,
    # not silently succeed against an already-abandoned row.
    r = client.post(f"/v1/workout-sessions/{first['id']}/finish", headers=user["headers"])
    assert r.status_code == 409


def test_finish_computes_a_real_duration(make_user, client):
    user = make_user()
    started = client.post(
        "/v1/workout-sessions", json={"activity_types": ["walk"]}, headers=user["headers"],
    ).get_json()
    r = client.post(f"/v1/workout-sessions/{started['id']}/finish", headers=user["headers"])
    assert r.status_code == 200
    body = r.get_json()
    assert body["duration_seconds"] >= 0
    assert body["planned_activity_count"] == 1
    assert body["completed_activity_count"] == 0


def test_finishing_the_same_session_twice_is_rejected(make_user, client):
    user = make_user()
    started = client.post(
        "/v1/workout-sessions", json={"activity_types": ["walk"]}, headers=user["headers"],
    ).get_json()
    client.post(f"/v1/workout-sessions/{started['id']}/finish", headers=user["headers"])
    r = client.post(f"/v1/workout-sessions/{started['id']}/finish", headers=user["headers"])
    assert r.status_code == 409


def test_finish_unknown_session_is_404(make_user, client):
    user = make_user()
    r = client.post(
        "/v1/workout-sessions/00000000-0000-0000-0000-000000000000/finish",
        headers=user["headers"],
    )
    assert r.status_code == 404


def test_finish_another_users_session_is_404_not_403(make_user, client):
    """Not found, not forbidden — doesn't confirm the session id belongs to
    someone else at all, same convention as custom-exercise ownership checks
    elsewhere in this codebase."""
    owner = make_user()
    intruder = make_user()
    started = client.post(
        "/v1/workout-sessions", json={"activity_types": ["walk"]}, headers=owner["headers"],
    ).get_json()
    r = client.post(f"/v1/workout-sessions/{started['id']}/finish", headers=intruder["headers"])
    assert r.status_code == 404


def test_logging_during_a_session_increments_its_completed_count(make_user, client):
    user = make_user()
    started = client.post(
        "/v1/workout-sessions",
        json={"activity_types": ["walk", "glute_bridge"]},
        headers=user["headers"],
    ).get_json()
    r = client.post(
        "/v1/activities",
        json={"activity_type": "walk", "amount": 1.0, "sets": 1,
              "workout_session_id": started["id"]},
        headers=user["headers"],
    )
    assert r.status_code == 201
    finished = client.post(
        f"/v1/workout-sessions/{started['id']}/finish", headers=user["headers"],
    ).get_json()
    assert finished["completed_activity_count"] == 1


def test_logging_against_an_unknown_session_id_is_rejected(make_user, client):
    user = make_user()
    r = client.post(
        "/v1/activities",
        json={"activity_type": "walk", "amount": 1.0, "sets": 1,
              "workout_session_id": "00000000-0000-0000-0000-000000000000"},
        headers=user["headers"],
    )
    assert r.status_code == 404


def test_logging_against_an_already_finished_session_is_rejected(make_user, client):
    user = make_user()
    started = client.post(
        "/v1/workout-sessions", json={"activity_types": ["walk"]}, headers=user["headers"],
    ).get_json()
    client.post(f"/v1/workout-sessions/{started['id']}/finish", headers=user["headers"])
    r = client.post(
        "/v1/activities",
        json={"activity_type": "walk", "amount": 1.0, "sets": 1,
              "workout_session_id": started["id"]},
        headers=user["headers"],
    )
    assert r.status_code == 409


def test_duplicate_replay_does_not_double_count_the_session(make_user, client):
    """The same offline-replay dedupe (client_entry_id) that already
    protects against double-logging must also protect the session's
    completed_activity_count from counting a replay twice."""
    user = make_user()
    started = client.post(
        "/v1/workout-sessions", json={"activity_types": ["walk"]}, headers=user["headers"],
    ).get_json()
    payload = {"activity_type": "walk", "amount": 1.0, "sets": 1,
               "workout_session_id": started["id"], "client_entry_id": "replay-1"}
    first = client.post("/v1/activities", json=payload, headers=user["headers"])
    second = client.post("/v1/activities", json=payload, headers=user["headers"])
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.get_json()["logged"][0]["duplicate"] is True
    finished = client.post(
        f"/v1/workout-sessions/{started['id']}/finish", headers=user["headers"],
    ).get_json()
    assert finished["completed_activity_count"] == 1


def test_only_one_active_session_per_user_at_the_database_level(make_user, client):
    """Belt-and-suspenders check on the partial unique index itself, not just
    the service-level self-healing logic — insert a second 'active' row
    directly and confirm the database refuses it."""
    user = make_user()
    client.post("/v1/workout-sessions", json={"activity_types": ["walk"]}, headers=user["headers"])
    with session_scope() as s:
        s.add(WorkoutSession(user_id=user["user_id"], planned_activity_count=1))
        try:
            s.flush()
            raised = False
        except Exception:
            raised = True
            s.rollback()
    assert raised, "a second 'active' WorkoutSession row for the same user must violate the DB constraint"
