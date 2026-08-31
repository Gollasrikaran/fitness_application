"""Module 5 (5.4) — the daily quota counter.

Shared table with voice_llm (12.6) and escalation_confirm (found live, third-pass
code audit — escalation_confirmation's own separate, much larger daily cap, kept
apart from rehab_llm's 5-message limit so confirming a progression bump never eats
into a user's real questions) even though only rehab_llm/escalation_confirm are
written here today — the separate-bucket design lives in the quota_type column,
not in separate tables, so none of these can ever accidentally share a counter.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class RehabQuota(Base):
    __tablename__ = "user_quota_counters"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    quota_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "quota_type IN ('rehab_llm','voice_llm','escalation_confirm')", name="quota_type_known"),
        CheckConstraint("count >= 0", name="quota_count_nonneg"),
    )


class RehabMemory(Base):
    """5.7 — cross-session chat memory, deliberately NOT a raw transcript.

    Each row is a compact, model-generated extraction of one exchange: a short
    summary, which approved exercises (if any) the answer named, and whether
    the user's own message indicates the pain is persisting/worsening despite
    guidance already given. That's enough to (a) give future answers real
    continuity and (b) let the app itself notice a recurring problem — without
    permanently storing verbatim health-related chat text.
    """
    __tablename__ = "rehab_memory"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # The user's selected condition(s) at the time of this exchange — lets the
    # "pain keeps persisting" count below be scoped per condition, not just
    # per user (a gout flare persisting doesn't mean a separate back problem is).
    condition_codes: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    exercises_mentioned: Mapped[list[str]] = mapped_column(ARRAY(String(128)), nullable=False, default=list)
    pain_persisting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class RehabChatLog(Base):
    """The actual conversation transcript, for redisplaying to the SAME user —
    a different job from RehabMemory above, which is deliberately a compact
    summary, not a transcript. Showing someone their own past messages back to
    them isn't a new exposure (they already said it once); this exists purely
    so the chat screen has something to redraw on login, instead of the
    conversation silently resetting to blank every time the page reloads.
    One row per real exchange, never edited, kept indefinitely per account —
    not per day, not per login.
    """
    __tablename__ = "rehab_chat_log"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    # Text, not a capped VARCHAR: chat_complete's max_tokens (2000) can produce
    # an answer past a few thousand characters, and a length cap here would
    # risk the exact "insert silently fails on the very thing meant to be
    # durable" bug already found and fixed once this session for AppIssue.path.
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
