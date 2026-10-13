"""Permanent regression guard for a found-live bug: a reps-type activity's
per-set targets (UserProgram.set_targets) displayed as a fractional value
("Set 1: 12.34") instead of a whole number of reps — something nobody can
actually perform a fraction of. Fixed in app/progression/service.py by
rounding with _round_reps (plain half-up to a whole number) in both places
that write set_targets, instead of a generic round(v, 2):
  - start_per_set_tracking_if_needed (seeding the very first set_targets)
  - _sync_entry_from_sets (every subsequent per-set recompute)

This test calls both functions directly with inputs chosen to produce a
non-whole raw value (12.342726, matching the exact value found live) and
asserts the stored set_targets are always whole numbers — so a future edit
to either function that reintroduces fractional reps fails CI immediately,
instead of surfacing months later as a screenshot from a live user.

Note: the fix only prevents NEW fractional values from being written: data
already stored before the fix was deployed stays wrong until something
re-triggers one of these two functions (or a one-off backfill runs — see
scripts/fix_fractional_reps_set_targets.py). This test guards the code path,
not already-existing rows.
"""
from decimal import Decimal

from app.platform.db import session_scope
from app.profile.models import UserProgram
from app.progression.service import _sync_entry_from_sets, start_per_set_tracking_if_needed

ACTIVITY = "glute_bridge"


def _all_whole(values) -> bool:
    return all(Decimal(v) == Decimal(v).to_integral_value() for v in values)


def test_start_per_set_tracking_seeds_whole_numbers_from_a_fractional_average(make_user):
    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        # The exact kind of value a weekly-average computation produces —
        # never a value a user could type in directly.
        entry.target_amount = Decimal("12.34")
        entry.internal_target_amount = Decimal("12.342726")
        s.flush()
        start_per_set_tracking_if_needed(s, user["user_id"], ACTIVITY)
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        assert _all_whole(entry.set_targets), entry.set_targets
        assert [float(v) for v in entry.set_targets] == [12.0, 12.0]


def test_sync_entry_from_sets_rounds_fractional_targets_to_whole_numbers(make_user):
    user = make_user()
    with session_scope() as s:
        entry = s.get(UserProgram, (user["user_id"], ACTIVITY))
        _sync_entry_from_sets(
            entry,
            targets=[12.342726, 26.5, 9.499999],
            internal=[12.342726, 26.5, 9.499999],
        )
        assert _all_whole(entry.set_targets), entry.set_targets
        assert [float(v) for v in entry.set_targets] == [12.0, 27.0, 9.0]  # half-up, not banker's
        assert Decimal(entry.target_amount) == entry.target_amount.to_integral_value()
