"""Module 15 (Progression Engine) — RLM design doc §4, §8.

One table: the audit trail for the weekly diminishing-curve job. The job itself
writes straight to the existing `UserProgram.target_amount` (Module 14) — this
table exists purely so "why did my target change?" (15.6) is answerable.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base


class ProgressionHistory(Base):
    """15.6 — one row per weekly run per program entry, whatever the outcome.

    `curve_pct` is the diminishing-curve's raw output before guard clamping;
    `adherence_pct` is the window adherence that drove the 15.3 rule. Keeping
    both separate from what was actually applied (`old_target`/`new_target`)
    lets a later "why did this change" view show the trend alongside what the
    guards did to it (design doc §8).
    """
    __tablename__ = "progression_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_type: Mapped[str] = mapped_column(
        String(64), ForeignKey("activity_taxonomy.activity_type"), nullable=False)

    old_target: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    new_target: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    adherence_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    curve_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)

    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "reason IN ('curve','hold','reduce','floor','escalation','double_progression')",
            name="ph_reason_known"),
        Index("ix_progression_history_user_activity", "user_id", "activity_type"),
    )
