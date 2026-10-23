"""Chat turns: the readable record of every conversation (store.models.Message)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from store.models import Message


def save_turn(db: Session, thread_id: str, mode: str, patient_id: str, doctor_id: str | None,
              question: str, reply: str, meta: dict) -> None:
    common = {"thread_id": thread_id, "mode": mode, "patient_id": patient_id, "doctor_id": doctor_id}
    db.add(Message(**common, role="user", content=question))
    db.add(Message(**common, role="assistant", content=reply, meta=meta))


def history(db: Session, thread_id: str, limit: int = 200) -> list[dict]:
    """The thread's latest messages, oldest first, in the shape the app shows."""
    rows = db.scalars(select(Message).where(Message.thread_id == thread_id)
                      .order_by(Message.id.desc()).limit(limit)).all()
    return [{"role": m.role, "content": m.content, "meta": m.meta,
             "at": m.created_at.isoformat()} for m in reversed(rows)]
