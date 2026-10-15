from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ProfileIn(BaseModel):
    age: int = Field(ge=18, le=100)  # adults only, same rule as the main app
    sex: str = Field(pattern="^(male|female|other)$")
    height_cm: float | None = Field(default=None, ge=100, le=250)
    weight_kg: float | None = Field(default=None, ge=25, le=300)
    experience: str = Field(default="beginner", pattern="^(beginner|intermediate|active)$")
    # Closed list only (codes from /conditions) — never free text.
    conditions: list[str] = Field(default_factory=list, max_length=10)


class ProgressIn(BaseModel):
    activity_type: str
    sets: int = Field(default=1, ge=1, le=20)
    amount: float = Field(gt=0, le=1000)
    pain_level: int | None = Field(default=None, ge=0, le=10)
    logged_on: date | None = None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class PlanExercise(BaseModel):
    activity_type: str
    sets: int = Field(ge=1, le=20)
    amount: float = Field(gt=0, le=1000)
    notes: str = Field(default="", max_length=300)


class PlanIn(BaseModel):
    instructions: str = Field(min_length=1, max_length=4000)
    exercises: list[PlanExercise] = Field(default_factory=list, max_length=20)


class PlanFeedbackIn(BaseModel):
    """The patient finds their current plan too hard. No free-text parsing:
    which exercises (empty = all of them) and the pain, if any, come as fields."""
    activity_types: list[str] = Field(default_factory=list, max_length=20)
    pain_level: int | None = Field(default=None, ge=0, le=10)
    note: str | None = Field(default=None, max_length=1000)


class ApproveIn(BaseModel):
    """Leave both out to approve the draft as it is; send either to edit it."""
    instructions: str | None = Field(default=None, min_length=1, max_length=4000)
    exercises: list[PlanExercise] | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=1000)


class RejectIn(BaseModel):
    note: str = Field(min_length=1, max_length=1000)
