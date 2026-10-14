"""Database tables.

Reference data (conditions, exercises, safety rules) is copied from the main
app's reviewed CSVs by `python -m app.seed`; everything else is per user.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Reference data ──────────────────────────────────────────────────────────

class Condition(Base):
    __tablename__ = "conditions"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    # "supported" = the AI may give self-care guidance; "refer" = always a doctor.
    bucket: Mapped[str] = mapped_column(String(16))
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class Exercise(Base):
    __tablename__ = "exercises"
    activity_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    amount_unit: Mapped[str] = mapped_column(String(16))
    default_sets: Mapped[int] = mapped_column(Integer, default=1)
    default_amount: Mapped[float] = mapped_column(Float, default=1)
    per_side: Mapped[bool] = mapped_column(default=False)


class SafetyRule(Base):
    __tablename__ = "safety_rules"
    __table_args__ = (UniqueConstraint("condition_code", "activity_type"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condition_code: Mapped[str] = mapped_column(ForeignKey("conditions.code"))
    activity_type: Mapped[str] = mapped_column(ForeignKey("exercises.activity_type"))
    verdict: Mapped[str] = mapped_column(String(8))  # safe | modify | avoid
    note: Mapped[str] = mapped_column(Text, default="")


# ── Users ───────────────────────────────────────────────────────────────────

class User(Base):
    """Our side of a Supabase Auth account: same id, plus the role. Passwords
    and email verification live in Supabase (auth.users), never here."""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # = Supabase auth user id
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="patient")  # patient | doctor
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    profile: Mapped["Profile | None"] = relationship(back_populates="user", uselist=False)
    conditions: Mapped[list["UserCondition"]] = relationship(cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    age: Mapped[int] = mapped_column(Integer)
    sex: Mapped[str] = mapped_column(String(16))
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience: Mapped[str] = mapped_column(String(16), default="beginner")  # beginner | intermediate | active
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="profile")


class UserCondition(Base):
    __tablename__ = "user_conditions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    condition_code: Mapped[str] = mapped_column(ForeignKey("conditions.code"), primary_key=True)


# ── Weekly progress ─────────────────────────────────────────────────────────

class ProgressLog(Base):
    __tablename__ = "progress_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    activity_type: Mapped[str] = mapped_column(ForeignKey("exercises.activity_type"))
    sets: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[float] = mapped_column(Float)  # per set, in the exercise's amount_unit
    pain_level: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-10 after the session
    logged_on: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ── Agent conversation and escalation ───────────────────────────────────────

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | doctor
    content: Mapped[str] = mapped_column(Text)
    # On assistant messages: what the agent decided for this turn.
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exercises: Mapped[list | None] = mapped_column(JSON, nullable=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class MemoryNote(Base):
    """Durable facts the agent learned in chat ("pain started after lifting a
    suitcase"), so they stay in context after the message itself has scrolled
    out of the recent-history window."""
    __tablename__ = "memory_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    note: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Case(Base):
    """A problem forwarded to a doctor. One open case per patient at a time;
    later escalations update it instead of piling up duplicates."""
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | plan_given | closed
    urgency: Mapped[str] = mapped_column(String(16), default="routine")  # emergency | priority | routine
    reason: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)  # the agent's hand-off note for the doctor
    triggers: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship()
    plans: Mapped[list["DoctorPlan"]] = relationship(back_populates="case", order_by="DoctorPlan.created_at")


class DoctorPlan(Base):
    __tablename__ = "doctor_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    instructions: Mapped[str] = mapped_column(Text)
    # [{activity_type, sets, amount, notes}] — a doctor may prescribe any
    # catalogue exercise; their clinical judgement overrides the safety grid.
    exercises: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    case: Mapped[Case] = relationship(back_populates="plans")
    doctor: Mapped[User] = relationship(foreign_keys=[doctor_id])
