"""Tables in the agent's store (schema agent_tmp).

Patients and doctors live in the clinic database; here they are just ids
(clinic patient.id and user.id), so there are no user tables.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from store.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Reference data (data/*.csv merged with the reference DB, see store/seed.py) ─
# Rebuilt on every start, so nothing else may point at these rows by foreign key.

class Condition(Base):
    __tablename__ = "conditions"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    bucket: Mapped[str] = mapped_column(String(16))  # supported | refer
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")


class Exercise(Base):
    __tablename__ = "exercises"
    activity_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    prescription_type: Mapped[str] = mapped_column(String(16), default="reps")  # reps | hold | distance
    amount_unit: Mapped[str] = mapped_column(String(16))
    default_sets: Mapped[int] = mapped_column(Integer, default=1)
    default_amount: Mapped[float] = mapped_column(Float, default=1)
    max_sets: Mapped[int] = mapped_column(Integer, default=1)
    max_amount: Mapped[float] = mapped_column(Float, default=1)
    per_side: Mapped[bool] = mapped_column(Boolean, default=False)
    rest_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progression_step: Mapped[float] = mapped_column(Float, default=1)
    priority_order: Mapped[int] = mapped_column(Integer, default=0)
    # For the patient's plan page, from the reference DB
    instructions: Mapped[list] = mapped_column(JSON, default=list)  # steps, in order
    images: Mapped[list] = mapped_column(JSON, default=list)  # demo image URLs


class SafetyRule(Base):
    __tablename__ = "safety_rules"
    __table_args__ = (UniqueConstraint("condition_code", "activity_type"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condition_code: Mapped[str] = mapped_column(ForeignKey("conditions.code"))
    activity_type: Mapped[str] = mapped_column(ForeignKey("exercises.activity_type"))
    verdict: Mapped[str] = mapped_column(String(8))  # safe | modify | avoid
    note: Mapped[str] = mapped_column(Text, default="")
    usefulness_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ConditionAlias(Base):
    """How the clinic writes one of our conditions (data/condition_aliases.csv).

    source: long_term_condition (the clinic's condition list, exact name) |
            health_history (questionnaire key) | text (a phrase in a diagnosis
            or chief complaint, matched as whole words).
    code: one of our condition codes, or bp_any / diabetes_any, which the
    safety rules turn into controlled or not from the recent vital flags."""
    __tablename__ = "condition_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(24))
    phrase: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default="")


class WarningComplaint(Base):
    """A chief complaint that sends the patient to a doctor
    (data/warning_complaints.csv), e.g. chest pain."""
    __tablename__ = "warning_complaints"
    phrase: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[str] = mapped_column(String(64))


# ── The agent's own data ────────────────────────────────────────────────────

class Assessment(Base):
    """One run of the assessment (agent/assess.py): what the rules and the AI
    found in the patient's record, and whether a doctor must write the plan."""
    __tablename__ = "assessments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(String(36), index=True)
    doctor_id: Mapped[str] = mapped_column(String(36))  # who asked for it
    codes: Mapped[list] = mapped_column(JSON, default=list)  # final condition codes
    conditions: Mapped[list] = mapped_column(JSON, default=list)  # [{code, name, bucket, found_by, complaint_only, evidence}]
    severity: Mapped[str] = mapped_column(String(16))  # mild | moderate | severe
    severe_reasons: Mapped[list] = mapped_column(JSON, default=list)
    problem: Mapped[str] = mapped_column(Text, default="")
    body_area: Mapped[str] = mapped_column(Text, default="")
    concerns: Mapped[list] = mapped_column(JSON, default=list)
    missing: Mapped[list] = mapped_column(JSON, default=list)
    unmapped: Mapped[list] = mapped_column(JSON, default=list)  # clinic conditions with no alias
    warnings: Mapped[list] = mapped_column(JSON, default=list)  # warning complaints in recent visits
    ai_status: Mapped[str] = mapped_column(String(16))  # ok | failed
    ai_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # the AI's raw answer, for audit
    dropped: Mapped[list] = mapped_column(JSON, default=list)  # AI findings rejected by the checks, and why
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Message(Base):
    """Every chat turn, as shown in the app. The agent's working memory is
    LangGraph's checkpointer (its own tables in this schema); this table is
    the readable record of what was said and what the agent decided."""
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(128), index=True)  # agent.main.thread_id()
    mode: Mapped[str] = mapped_column(String(16))  # patient | doctor
    patient_id: Mapped[str] = mapped_column(String(36), index=True)
    doctor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # the agent's decision (assistant turns)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Case(Base):
    """Something the agent passed to a doctor. One open case per patient;
    later hand-offs add to it."""
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | closed
    urgency: Mapped[str] = mapped_column(String(16), default="routine")  # emergency | priority | routine
    reason: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    triggers: Mapped[list] = mapped_column(JSON, default=list)
    closed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)  # doctor id
    close_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Plan(Base):
    """A plan the patient follows. Every row was approved by a doctor."""
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(String(36), index=True)
    doctor_id: Mapped[str] = mapped_column(String(36))
    instructions: Mapped[str] = mapped_column(Text)
    exercises: Mapped[list] = mapped_column(JSON, default=list)  # [{activity_type, name, unit, sets, amount, notes}]
    conditions: Mapped[list] = mapped_column(JSON, default=list)  # condition codes it was made for
    proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlanProposal(Base):
    """A plan drafted for a doctor to review. Nothing here reaches the
    patient until a doctor approves it, which copies it into Plan.

    source: "rules" (built by store.plans, no AI) | "doctor" (the rules can't
    draft one, e.g. a refer condition, so the doctor writes it)."""
    __tablename__ = "plan_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # starter | easier | update
    source: Mapped[str] = mapped_column(String(16))  # rules | doctor
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected | superseded
    instructions: Mapped[str] = mapped_column(Text)
    exercises: Mapped[list] = mapped_column(JSON, default=list)
    changes: Mapped[list] = mapped_column(JSON, default=list)  # [{activity_type, name, from, to, note}]
    reason: Mapped[str] = mapped_column(Text)  # why it was drafted, for the doctor
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    patient_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    based_on_plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    approved_plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)  # doctor id
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
