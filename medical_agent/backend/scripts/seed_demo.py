"""Demo accounts for trying the rule-drafted plans end to end. Admin-only:
uses the service role key.

    python scripts/seed_demo.py

Creates (or resets) one doctor and seven patients on @example.com, all with
one shared password printed at the end. Each patient is left in a different
state of the plan flow; the drafts and plans come from app.agent.plans, the
same code the API runs. Re-running wipes and rebuilds the demo patients
only; nobody else's data is touched.
"""
from __future__ import annotations

import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete  # noqa: E402

from app.agent import context as ctx  # noqa: E402
from app.agent import plans  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Profile, ProgressLog, User, UserCondition  # noqa: E402
from app.seed import init_db  # noqa: E402
from scripts.create_doctor import _find_auth_user, _headers  # noqa: E402

DOCTOR = ("demo.doctor@example.com", "Asha Rao")

# email, name, age, sex, height, weight, experience, conditions, what the demo shows
PATIENTS = [
    ("demo.priya@example.com", "Priya (new, knee + low mood)", 28, "female", 158, 55, "beginner",
     ["arthritis_knee", "depression"], "Starter draft waiting for the doctor"),
    ("demo.ramesh@example.com", "Ramesh (68, back pain)", 68, "male", 170, 72, "beginner",
     ["chronic_back_pain"], "Starter draft with the age rule: lower doses"),
    ("demo.arjun@example.com", "Arjun (BMI 35, active)", 34, "male", 160, 90, "active",
     [], "Starter draft with the BMI rule: no running"),
    ("demo.lakshmi@example.com", "Lakshmi (heart problem)", 45, "female", 155, 60, "beginner",
     ["heart_condition"], "Refer condition: the doctor must write the plan"),
    ("demo.sanjay@example.com", "Sanjay (plan too hard)", 40, "male", 175, 78, "beginner",
     ["chronic_back_pain"], "Has a plan; asked for an easier one"),
    ("demo.meena@example.com", "Meena (new slip disc)", 52, "female", 160, 64, "intermediate",
     ["chronic_back_pain"], "Has a plan; then added a slip disc"),
    ("demo.kiran@example.com", "Kiran (on a plan)", 30, "male", 178, 70, "beginner",
     ["sprain_strain"], "Has a plan and two weeks of logs: try 'too hard' yourself"),
]


def auth_account(email: str, name: str, password: str) -> str:
    """Create the Supabase Auth user, or reset its password. Returns its id."""
    found = _find_auth_user(email)
    if found is None:
        r = httpx.post(f"{settings.supabase_url}/auth/v1/admin/users", headers=_headers(), timeout=30,
                       json={"email": email, "password": password, "email_confirm": True,
                             "user_metadata": {"name": name}})
    else:
        r = httpx.put(f"{settings.supabase_url}/auth/v1/admin/users/{found['id']}", headers=_headers(),
                      timeout=30, json={"password": password, "email_confirm": True})
    if r.status_code >= 300:
        sys.exit(f"Supabase refused {email}: HTTP {r.status_code} {r.text[:300]}")
    return r.json()["id"]


def add_logs(db, user_id: str, rows: list[tuple[int, str, int, float, int | None]]) -> None:
    """rows: (days ago, exercise, sets, amount, pain)."""
    for days_ago, activity, sets, amount, pain in rows:
        db.add(ProgressLog(user_id=user_id, activity_type=activity, sets=sets, amount=amount, pain_level=pain,
                           logged_on=date.today() - timedelta(days=days_ago)))


def set_conditions(db, user: User, codes: list[str]) -> None:
    db.execute(delete(UserCondition).where(UserCondition.user_id == user.id))
    db.add_all(UserCondition(user_id=user.id, condition_code=c) for c in codes)
    db.flush()
    db.refresh(user)


def main() -> None:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        sys.exit("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env first.")
    password = "Demo-" + secrets.token_urlsafe(9)
    init_db()

    ids = {email: auth_account(email, name, password) for email, name, *_ in [DOCTOR, *PATIENTS]}
    with SessionLocal() as db:
        doctor = db.get(User, ids[DOCTOR[0]])
        if doctor is None:
            doctor = User(id=ids[DOCTOR[0]], email=DOCTOR[0], name=DOCTOR[1], role="doctor")
            db.add(doctor)
        doctor.role, doctor.name = "doctor", DOCTOR[1]
        # Start the demo patients from nothing (cascades to all their rows).
        db.execute(delete(User).where(User.email.in_([p[0] for p in PATIENTS])))
        db.flush()

        users = {}
        for email, name, age, sex, height, weight, experience, codes, _ in PATIENTS:
            user = User(id=ids[email], email=email, name=name, role="patient")
            db.add(user)
            db.add(Profile(user_id=user.id, age=age, sex=sex, height_cm=height, weight_kg=weight,
                           experience=experience))
            db.flush()
            set_conditions(db, user, codes)
            plans.on_profile_saved(db, user, [])  # what PUT /profile does: drafts the starter plan
            users[email] = user

        def approve_starter(email: str, exercises: list[dict] | None = None):
            draft = plans.pending_proposal(db, users[email].id)
            return plans.approve(db, draft, doctor, draft.instructions, exercises or draft.exercises,
                                 "Looks good, start gently.")

        # Sanjay: approved plan, two weeks of logs, then "glute bridges are too hard".
        sanjay = users["demo.sanjay@example.com"]
        plan = approve_starter(sanjay.email)
        add_logs(db, sanjay.id, [(12, "walk", 1, 1, 2), (11, "glute_bridge", 2, 5, 3), (9, "walk", 1, 1, 2),
                                 (8, "glute_bridge", 2, 5, 3), (5, "glute_bridge", 2, 5, 5),
                                 (3, "walk", 1, 1, 3), (2, "glute_bridge", 2, 4, 5)])
        plans.request_easier(db, sanjay, plan, ["glute_bridge"],
                             "Bridges make my lower back ache by the second set.")

        # Meena: the doctor added a hamstring stretch; then she ticks "slip disc", where it's "avoid".
        meena = users["demo.meena@example.com"]
        draft = plans.pending_proposal(db, meena.id)
        approve_starter(meena.email, draft.exercises[:4] + [
            {"activity_type": "hamstring_stretch", "name": "Seated Hamstring Stretch", "unit": "sec",
             "sets": 2, "amount": 15, "notes": "Gentle, no bouncing"}])
        add_logs(db, meena.id, [(6, "walk", 1, 1, 2), (4, "hamstring_stretch", 2, 15, 2), (1, "walk", 1, 1, 1)])
        old = ctx.condition_codes(meena)
        set_conditions(db, meena, ["chronic_back_pain", "herniated_disk"])
        plans.on_profile_saved(db, meena, old)  # what PUT /profile does: drafts the update

        # Kiran: an approved plan and steady logs, nothing pending.
        kiran = users["demo.kiran@example.com"]
        approve_starter(kiran.email)
        add_logs(db, kiran.id, [(d, "walk", 1, 1, 2) for d in (13, 11, 9, 6, 4, 2)]
                 + [(d, "ankle_circles", 2, 5, 2) for d in (12, 8, 5, 1)])
        db.commit()

    print(f"Password for every demo account: {password}\n")
    print(f"Doctor portal (/doctor):  {DOCTOR[0]}")
    print("Patient app:")
    for email, _, *_rest, shows in PATIENTS:
        print(f"  {email:<28} {shows}")


if __name__ == "__main__":
    main()
