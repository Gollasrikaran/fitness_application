"""Opening and updating the one open doctor case a patient can have."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agent import context as ctx
from app.models import Case, User

log = logging.getLogger("medical_agent.cases")

URGENCY_RANK = {"routine": 0, "priority": 1, "emergency": 2}


def upsert_case(db: Session, user: User, urgency: str, reason: str, summary: str,
                triggers: list[str]) -> Case:
    case = ctx.open_case(db, user.id)
    if case is None:
        case = Case(user_id=user.id, urgency=urgency, reason=reason, summary=summary, triggers=triggers)
        db.add(case)
        db.flush()
        log.warning("New %s case %s opened", urgency, case.id)  # ids only: no health data in logs
    else:
        if URGENCY_RANK[urgency] > URGENCY_RANK[case.urgency]:
            case.urgency = urgency
            log.warning("Case %s raised to %s", case.id, urgency)
        case.reason = reason
        # Keep earlier hand-offs: a doctor needs the whole story, not just the latest turn.
        stamp = datetime.now(timezone.utc).strftime("%d %b %H:%M UTC")
        case.summary = f"{case.summary}\n\nUpdate {stamp}: {summary}"
        case.triggers = sorted(set(case.triggers or []) | set(triggers))
    return case
