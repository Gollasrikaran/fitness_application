"""Signup, login, email verification and password reset all happen in the
browser against Supabase Auth. This router only tells the frontend who the
signed-in user is and which portal they belong to."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import current_user
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role,
            "has_profile": user.profile is not None}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
