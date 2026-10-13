"""Regression test for a found-live bug: amount validation only checked
`amount <= 0`, but ActivityLog.amount/set_amounts are stored as
Numeric(10,2) — a value like 0.004 passed validation, then rounded to 0.00
at storage, which the database's own CHECK(amount > 0) constraint then
rejected as an uncaught IntegrityError (500) instead of a clean 422. Fixed
in app/profile/service.py by rejecting anything that rounds to zero at the
precision it's actually stored at, not just anything mathematically <= 0."""
import pytest

from app.platform.db import session_scope
from app.platform.errors import ValidationError
from app.profile import service


def test_tiny_amount_raises_clean_validation_error_not_a_crash(make_user):
    user = make_user(condition_codes=["none"])
    with session_scope() as s:
        with pytest.raises(ValidationError, match="greater than zero"):
            service.log_activity(s, user["user_id"], activity_type="walk", amount=0.004, sets=1)


def test_tiny_set_amounts_value_raises_clean_validation_error(make_user):
    user = make_user(condition_codes=["none"])
    with session_scope() as s:
        with pytest.raises(ValidationError, match="greater than zero"):
            service.log_activity(s, user["user_id"], activity_type="glute_bridge", set_amounts=[0.004])
