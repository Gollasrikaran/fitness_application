"""Module 5 (5.4) — the daily quota counter.

Shared table with voice_llm (12.6) even though only rehab_llm is written here — the
separate-bucket design lives in the quota_type column, not in separate tables, so
the two features can never accidentally share a counter (5.4 / 12.6 note).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base


class RehabQuota(Base):
    __tablename__ = "user_quota_counters"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    quota_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("quota_type IN ('rehab_llm','voice_llm')", name="quota_type_known"),
        CheckConstraint("count >= 0", name="quota_count_nonneg"),
    )
