"""Module 15 (Progression Engine) — RLM design doc §4.

Rule-based arithmetic, no LLM (15.5). Two pieces:

- `compute_curve_increase` — the pure diminishing-curve formula (§4.1), unit-testable
  with no DB dependency.
- `run_weekly_progression` — the batch job: reads adherence from `activity_logs`,
  applies the 15.3 rule table, clamps through the 15.4 guard chain, writes the new
  target and a `ProgressionHistory` row.

Two things the design doc assumes but this codebase does not yet have, so this job
does not attempt them (nothing to skip is not the same as skipping it):

- 15.3's "open discomfort episode -> hold" row: Module 14.6 (discomfort reporting)
  is not built. No entry can currently have an open episode, so this row never
  fires here. Wire it in when 14.6 exists.
- 15.2's "entries in calibration are skipped": Module 14.9 (calibration) is not
  built either — `UserProgram.status` only has `active`/`suspended`, there is no
  `calibrating` state to check.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import ActivityTaxonomy, SafetyGridCell
from app.platform.errors import NotFound
from app.profile.models import ActivityLog, UserCondition, UserProgram
from app.profile.service import today_ist
from app.progression.models import ProgressionHistory

# Phase 7 observability: which guard fired, by how much it reduced a proposal —
# the tuning data the plan calls for. This is operational logging (this
# codebase's existing logging.getLogger(__name__) convention — see
# app/platform/redis_clients.py), not a database write: `AppIssue`
# (app/platform/models.py) is explicitly scoped to genuine unexpected server
# errors only, and a guard clamping a value is normal, working-as-designed
# behavior, not an issue — writing routine clamps into that table would bury
# real errors in noise it was deliberately built to stay narrow against.
_log = logging.getLogger(__name__)

# Per-activity override lives on ActivityTaxonomy.curve_k (nullable); this is the
# app-wide fallback until a reviewer sets per-activity values. Chosen so the very
# first weekly increase (week=1) lands close to the old flat-rate's upper bound
# (~10%), matching 15.3's beginner default before it tapers on later weeks.
DEFAULT_CURVE_K = 0.15

# 15.4 "absolute cap per adjustment" — set above the old flat 5-10% ceiling since
# the curve is *meant* to start more aggressive than the flat rate, but still
# bounded so a misconfigured k cannot produce a runaway jump.
MAX_ADJUSTMENT_PCT = 0.20

# 15.2's adherence window. The design doc's lagged Wed-for-week-ending-Sunday
# scheduling (15.2) is a scheduling concern (see scripts/run_weekly_progression.py),
# not something this function needs to know about — it just looks at a trailing
# window ending "today" whenever it's called.
ADHERENCE_WINDOW_DAYS = 7

# 15.2 "adherence is capped at 150%" for progression purposes.
ADHERENCE_CAP = 1.5

# 15.3's "<50%" row reuses 14.6d's reduction formula per the design doc — but
# 14.6d (soreness reduction) isn't built in this codebase either, so there is no
# real formula to reuse yet. This is an explicit, documented flat default
# standing in for it, not a silent guess.
REDUCE_PCT = 0.10

# Reps-only double-progression ceiling (product decision, not a taxonomy
# revision): taxonomy.max_amount for reps-type activities (e.g. glute_bridge's
# 15) is the *conservative rehab-onset* ceiling, reviewed for someone just
# starting out. It was never meant to be a permanent lifetime cap — someone
# logging 100% adherence for months is not still a rehab beginner, and the
# diminishing curve alone cannot get them past it (see compute_curve_increase's
# own math: growth keeps shrinking every week, so a fixed low ceiling plus a
# vanishing growth rate means real users visibly plateau at single-digit reps
# after a year — found live, flagged, and this is the fix). Applies ONLY to
# prescription_type == "reps": hold/distance/duration activities keep using
# taxonomy.max_amount/max_sets exactly as before, untouched.
REPS_STANDARD_CEILING = 30.0
REPS_TRAILING_WINDOW_DAYS = 7
# Absolute per-set rep cap once a user is past their first set-bump — the
# ceiling for every cycle from the 2nd set onward (see _reps_cycle_ceiling).
REPS_HARD_CEILING = 50.0

# Explicit product decision, not a curve retune: compute_curve_increase's
# weekly % vanishes toward zero (see its own math — a compliant beginner
# would take on the order of 10^14 weeks to climb from 5 reps to the 30-rep
# standard ceiling). This is still exactly that same formula (a genuine log
# curve — a real ABSOLUTE jump every week that shrinks every week, not just a
# shrinking percentage on a still-growing base), just with a much higher,
# reps-only k: k such that baseline*(1+k*ln(6)) = 6*baseline, i.e.
# k = 5/ln(6) =~ 2.79 — so 5 weeks of compounding takes a compliant beginner
# from baseline to 6x baseline (5 -> 30 reps). The SAME k is reused for every
# later double-progression cycle too (an explicit product decision — later
# cycles climb much faster since 25->50 is a smaller range than 5->30 under
# the same steep curve, so a user strong enough to earn one bump chains
# through subsequent ones quickly).
#
# This k no longer feeds off the calendar week number at all for reps-type
# activities — see _reps_curve_step: the "week" fed into the curve is an
# EFFECTIVE week derived by inverting the curve against the user's real
# trailing-7-day average, so the whole trajectory (not just this week's
# target) continuously re-paces itself to what someone actually does,
# instead of a fixed calendar schedule.
REPS_FAST_TRACK_K = 5 / math.log(6)
# Double progression's own hard stop: once sets reach this, the cycle stops
# adding more (4 sets x 50 reps = 200/side is the true ceiling for a reps
# activity) — a set-count guard, independent of the per-set REPS_HARD_CEILING.
REPS_MAX_SETS = 4


def compute_curve_increase(baseline_target: float, week: int, k: float) -> float:
    """RLM design doc §4.1 — diminishing weekly increase percentage.

    capacity(week) = baseline_target * (1 + k * ln(1 + week))
    weekly_increase_pct = capacity(week) / capacity(week - 1) - 1

    `week` counts from the program entry's start (0-indexed). Week 0 is the
    entry's first week — there is no week -1 to compare against, so it returns 0
    (nothing to progress from yet). `baseline_target` cancels out of the ratio
    algebraically; it's kept as a parameter to match the design doc's formula
    and so a future caller that needs the absolute capacity value has it.
    """
    if week <= 0:
        return 0.0
    capacity_now = baseline_target * (1 + k * math.log(1 + week))
    capacity_prev = baseline_target * (1 + k * math.log(week))
    return capacity_now / capacity_prev - 1


def _week_number(added_at: datetime, today: date) -> int:
    started = added_at.date() if isinstance(added_at, datetime) else added_at
    return max(0, (today - started).days // 7)


def _window_adherence(session: Session, user_id: str, activity_type: str,
                       target_volume: float, today: date) -> float:
    """15.2 — completed volume ÷ target volume over the trailing window.

    No per-week expected-frequency is modeled anywhere in this codebase yet (the
    taxonomy has a per-session prescription, not a sessions-per-week count), so
    this reads as: of the sessions actually logged in the window, how close to
    the target volume was each one, averaged. No logs in the window scores 0%,
    not "no data" — a week with no activity is not adherence.
    """
    window_start = today - timedelta(days=ADHERENCE_WINDOW_DAYS)
    rows = session.scalars(
        select(ActivityLog).where(
            ActivityLog.user_id == user_id,
            ActivityLog.activity_type == activity_type,
            ActivityLog.local_date > window_start,
            ActivityLog.local_date <= today,
            ActivityLog.implausible.is_(False),  # 4.6 / 15.2
        )
    ).all()
    if not rows or target_volume <= 0:
        return 0.0
    ratios = [min(float(r.total_volume) / target_volume, ADHERENCE_CAP) for r in rows]
    return sum(ratios) / len(ratios)


def _sides(taxonomy: ActivityTaxonomy) -> int:
    return 2 if taxonomy.per_side else 1


def _tracking_amount(entry: UserProgram) -> float:
    """The real, continuous per-set amount the curve math treats as "current" —
    entry.internal_target_amount when it's been set, or entry.target_amount
    (the displayed value) the first time an entry is ever processed. This is
    what makes small weekly gains accumulate instead of resetting: see
    _volume_bounds and the internal_target_amount column's own docstring in
    app/profile/models.py."""
    return float(entry.internal_target_amount
                 if entry.internal_target_amount is not None else entry.target_amount)


def _reps_trailing_average(session: Session, user_id: str, activity_type: str,
                            today: date) -> float | None:
    """Trailing-7-day average of what the user actually logged per set
    (ActivityLog.amount_per_set), for the personal reps ceiling below. None
    when nothing real was logged in the window — the caller falls back to the
    standard ceiling rather than treating "no data" as "average of zero"."""
    window_start = today - timedelta(days=REPS_TRAILING_WINDOW_DAYS)
    rows = session.scalars(
        select(ActivityLog).where(
            ActivityLog.user_id == user_id,
            ActivityLog.activity_type == activity_type,
            ActivityLog.local_date > window_start,
            ActivityLog.local_date <= today,
            ActivityLog.implausible.is_(False),
        )
    ).all()
    if not rows:
        return None
    return sum(float(r.amount_per_set) for r in rows) / len(rows)


def _reps_cycle_ceiling(taxonomy: ActivityTaxonomy, entry: UserProgram) -> float:
    """The per-set reps ceiling for the CURRENT cycle: REPS_STANDARD_CEILING
    (30) while still on the taxonomy's default set count (the first cycle),
    REPS_HARD_CEILING (50) for every cycle after the first set-bump. A fixed,
    explicit two-stage ceiling — not a rolling average-based number — per the
    confirmed design: 30 is the real ceiling for the 2-set stage, 50 for
    every stage after."""
    if entry.target_sets == taxonomy.default_sets:
        return REPS_STANDARD_CEILING
    return REPS_HARD_CEILING


def _reps_cycle_baseline(session: Session, user_id: str, activity_type: str,
                          taxonomy: ActivityTaxonomy) -> float:
    """The CURRENT cycle's fixed starting point for the effective-week curve
    inversion (see _reps_curve_step) — taxonomy.default_amount for the first
    cycle, or whatever redistributed value the most recent double-progression
    bump reset to. Read from ProgressionHistory (the existing audit trail)
    rather than a new column: the most recent 'double_progression' row's
    new_target IS that reset value, by construction (_reps_curve_step writes
    it there)."""
    last_bump = session.scalars(
        select(ProgressionHistory)
        .where(ProgressionHistory.user_id == user_id,
               ProgressionHistory.activity_type == activity_type,
               ProgressionHistory.reason == "double_progression")
        .order_by(ProgressionHistory.applied_at.desc())
        .limit(1)
    ).first()
    if last_bump is not None:
        return float(last_bump.new_target)
    return float(taxonomy.default_amount)


def _reps_curve_step(session: Session, user_id: str, taxonomy: ActivityTaxonomy,
                      entry: UserProgram, today: date) -> tuple[float, bool, float]:
    """The reps-only fast-track weekly step (design confirmed in
    conversation): instead of feeding the calendar week number into the
    curve, invert the SAME curve equation against the user's real
    trailing-7-day average to find which "effective week" that average
    corresponds to, then read the curve ONE week further forward — so the
    whole trajectory re-paces itself to real behavior every week, not a
    fixed calendar schedule. An overachiever gets fast-forwarded; someone
    falling short gets a gentler, still-honest next step instead of a jump
    they've already proven they can't make.

    w_eff = exp((avg/baseline - 1) / k) - 1
    raw_target = baseline * (1 + k * ln(1 + w_eff + 1))

    If that raw_target would cross the CURRENT cycle's ceiling (30 for the
    first cycle, 50 after) AND the real average itself already crossed that
    ceiling, growth stops being expressed as more reps-per-set and becomes an
    extra set instead: target_sets += 1, and the new cycle's starting
    per-set reps is the real average redistributed across the new set count
    (avg * old_sets / new_sets) — using what was actually proven, not an
    arbitrary fixed reset. REPS_MAX_SETS is the hard stop on this repeating.

    Returns (new_volume, did_bump, raw_volume) — raw_volume is the
    PRE-clamp/pre-bump suggestion (raw_target * original sets * sides),
    purely for _log_if_clamped's requested-vs-applied observability; it is
    never itself written anywhere. Never regresses below old_volume — the
    trailing average is a rolling number and can legitimately read lower some
    week than what's already tracked; "reduce" (the <50%-adherence path) is
    the only path allowed to actually decrease a target, deliberately.
    """
    sides = _sides(taxonomy)
    old_sets = entry.target_sets
    old_volume = _tracking_amount(entry) * old_sets * sides
    baseline = _reps_cycle_baseline(session, user_id, entry.activity_type, taxonomy)
    ceiling_amount = _reps_cycle_ceiling(taxonomy, entry)
    avg = _reps_trailing_average(session, user_id, entry.activity_type, today)
    if avg is None:
        avg = _tracking_amount(entry)

    w_eff = math.exp((avg / baseline - 1) / REPS_FAST_TRACK_K) - 1
    raw_target = baseline * (1 + REPS_FAST_TRACK_K * math.log(1 + w_eff + 1))
    raw_volume = raw_target * old_sets * sides

    if avg > ceiling_amount and raw_target > ceiling_amount and old_sets < REPS_MAX_SETS:
        entry.target_sets = old_sets + 1
        # Found live (code audit): this redistribution used the raw average
        # with no cap, unlike the non-bump branch below which correctly caps
        # at ceiling_amount. _reps_trailing_average only excludes logs
        # flagged implausible, and that flag compares against
        # taxonomy.plausible_max_total — a much larger, unrelated number —
        # so a single extreme-but-plausible log could redistribute into a
        # prescription far above the hard ceiling itself. Cap at
        # REPS_HARD_CEILING specifically (not ceiling_amount, the ceiling
        # being LEFT): the entry always enters a cycle past the default set
        # count after a bump, so _reps_cycle_ceiling would resolve to the
        # hard ceiling for it regardless of which bump this is.
        new_per_set = min((avg * old_sets) / entry.target_sets, REPS_HARD_CEILING)
        return max(new_per_set * entry.target_sets * sides, old_volume), True, raw_volume

    new_per_set = min(raw_target, ceiling_amount)
    return max(new_per_set * entry.target_sets * sides, old_volume), False, raw_volume


def _volume_bounds(taxonomy: ActivityTaxonomy, entry: UserProgram, *,
                    reps_ceiling_amount: float | None = None) -> tuple[float, float, float]:
    """(old_volume, floor_volume, ceiling_volume) for one entry — the same
    default-half-floor (15.4) and taxonomy ceiling (see §11 gap #3: the real
    per-activity ceiling standing in for the design doc's abstract "3x band
    ceiling") that BOTH the weekly job below and the chat-confirmed escalation
    path (app/progression/service.py:apply_escalation) clamp against, kept in
    one place so the two write paths cannot silently drift apart.

    old_volume is built from the CONTINUOUS tracking amount (_tracking_amount),
    not the rounded/displayed target_amount — see that function's docstring
    for why: using the rounded value here is exactly what made rep-based
    exercises stall forever at 100% adherence (found live).

    reps_ceiling_amount overrides taxonomy.max_amount for the ceiling
    calculation, and uses the entry's CURRENT target_sets rather than
    taxonomy.max_sets — sets only grow one at a time, via _reps_curve_step
    (or apply_escalation's own bump check), not by assuming the taxonomy's
    max upfront. Callers pass this only for prescription_type == "reps";
    every other activity shape is unaffected and keeps using
    taxonomy.max_amount/max_sets exactly as before. It's floored at
    old_volume for the same reason _reps_curve_step never regresses below
    old_volume: it can block further growth, never claw back ground already
    earned."""
    sides = _sides(taxonomy)
    old_volume = _tracking_amount(entry) * entry.target_sets * sides
    default_volume = float(taxonomy.default_amount) * taxonomy.default_sets * sides
    if reps_ceiling_amount is not None:
        ceiling_volume = max(reps_ceiling_amount * entry.target_sets * sides, old_volume)
    else:
        ceiling_volume = float(taxonomy.max_amount) * taxonomy.max_sets * sides
    floor_volume = 0.5 * default_volume
    return old_volume, floor_volume, ceiling_volume


def _snap_to_progression_step(amount: float, taxonomy: ActivityTaxonomy) -> float:
    """4.0's reviewed `progression_step` exists for exactly this reason: a
    "reps" activity (glute_bridge, step=2) or "hold" activity (step=5 seconds)
    can only ever be prescribed in whole steps — "5.52 reps" is not something
    a user can do. Raw percentage math (compute_curve_increase) works in
    smooth curves, but the OUTPUT has to land on the same discrete grid double
    progression would produce (default_amount, +step, +2*step, ...), or on a
    real number for continuous units (distance/duration already have a small
    step like 0.2 km, so this applies uniformly rather than special-casing by
    unit). Found live: an account's real progression showed 5.0 -> 5.52 reps.

    Snapping this value ALONE would silently erase the fractional part every
    week (a real limitation this codebase hit live — every current activity's
    step is 20-50% of its own baseline, far more than a single week's ~10%
    growth, so a naive round-trip through this function could never cross a
    whole step, at any week, in either direction). That's why the CALLER
    never treats this function's output as the new tracking baseline —
    UserProgram.internal_target_amount (see its own docstring) keeps the
    unrounded value alive across weeks so partial progress keeps
    accumulating; only entry.target_amount (what's shown to the user) goes
    through this snap.
    """
    step = float(taxonomy.progression_step)
    default = float(taxonomy.default_amount)
    steps_from_default = round((amount - default) / step)
    return max(step, default + steps_from_default * step)


def _round_reps(amount: float) -> float:
    """Reps-only display rounding (explicit product decision, replacing
    _snap_to_progression_step for prescription_type == "reps"): a plain
    whole-number round, half-up (41.25 -> 41, 41.50 -> 42) — never Python's
    built-in round(), which rounds .5 to the nearest EVEN integer (round(41.5)
    == 42 by coincidence, but round(42.5) == 42, not 43). The average-based
    redistribution formula (_reps_curve_step) produces arbitrary decimals, not
    values that land on a fixed step lattice, so a plain integer round fits
    better than progression_step snapping for reps specifically — hold,
    distance, and duration activities keep _snap_to_progression_step exactly
    as before."""
    return math.floor(amount + 0.5)


def _apply_new_volume(entry: UserProgram, taxonomy: ActivityTaxonomy, new_volume: float) -> Decimal:
    """Writes BOTH halves of the dual-tracking fix in one place, so a caller
    can never update one without the other: target_amount gets the rounded,
    real, displayable value (unchanged behavior); internal_target_amount gets
    the full-precision raw value, unrounded, so next week's _volume_bounds
    starts from where this one actually left off rather than from whatever
    got rounded for display. Returns the new target_amount for convenience
    (ProgressionHistory.new_target wants it)."""
    raw_amount = new_volume / (entry.target_sets * _sides(taxonomy))
    entry.internal_target_amount = Decimal(str(round(raw_amount, 6)))
    if taxonomy.prescription_type == "reps":
        rounded = _round_reps(raw_amount)
    else:
        rounded = _snap_to_progression_step(raw_amount, taxonomy)
    entry.target_amount = Decimal(str(round(rounded, 2)))
    return entry.target_amount


# ProgressionHistory.curve_pct/adherence_pct are Numeric(6,2), max magnitude
# 9999.99. Found live (code audit): a plausible reviewer typo in a
# per-activity curve_k override (entering 150 instead of 0.15 — an easy
# mistake given how small the real default is), or an extreme trailing
# average feeding the reps fast-track path, could produce a raw percentage
# whose *100 representation overflows that column and raises a DB error at
# write time — this only affects the stored AUDIT value (the applied volume
# is independently guarded elsewhere), but the unguarded write still throws
# and could abort an entire batch run over a value nobody actually applied.
_HISTORY_PCT_LIMIT = 9999.99


def _clamp_for_history(pct: float) -> float:
    return max(-_HISTORY_PCT_LIMIT, min(_HISTORY_PCT_LIMIT, pct * 100))


def _log_if_clamped(*, path: str, user_id: str, activity_type: str,
                     requested_pct: float, applied_pct: float) -> None:
    """Phase 7 observability — see the module-level `_log` comment. Only logs
    when a guard actually changed the outcome, so this stays silent (and
    cheap) for the normal case where nothing needed clamping."""
    if abs(requested_pct - applied_pct) < 1e-6:
        return
    _log.warning(
        "progression guard clamped a change: path=%s user_id=%s activity_type=%s "
        "requested_pct=%.4f applied_pct=%.4f reduced_by_pct=%.4f",
        path, user_id, activity_type, requested_pct, applied_pct,
        requested_pct - applied_pct,
    )


def _is_safe_to_progress(session: Session, user_id: str, activity_type: str) -> bool:
    """13.3 safety-grid check, re-queried live every call — mirrors
    app/progression/analysis.py's _condition_gate (the on-demand chat path's
    own version of this same check) rather than importing it, to keep the
    two modules' cross-dependency one-directional. See run_weekly_progression
    for why this is needed: this batch job used to have no equivalent check
    at all."""
    verdicts = session.execute(
        select(SafetyGridCell.verdict)
        .join(UserCondition, UserCondition.condition_code == SafetyGridCell.condition_code)
        .where(UserCondition.user_id == user_id, SafetyGridCell.activity_type == activity_type)
    ).scalars().all()
    return all(v != "avoid" for v in verdicts)


def _already_progressed_today(session: Session, user_id: str, activity_type: str,
                               today: date) -> bool:
    """Found live (code audit): nothing previously stopped a second same-day
    invocation for this user/activity — a manual re-run, a retried scheduler
    trigger, or an overlapping run (more plausible now the scheduler fires
    daily instead of weekly, see scripts/run_weekly_progression.py) — from
    stacking a second week's change on top of the first. The reps fast-track
    path happened to be incidentally protected by its own never-regress
    floor; the generic non-reps guard-chain path had no such protection."""
    last_applied = session.scalar(
        select(ProgressionHistory.applied_at)
        .where(ProgressionHistory.user_id == user_id,
               ProgressionHistory.activity_type == activity_type)
        .order_by(ProgressionHistory.applied_at.desc())
        .limit(1)
    )
    return last_applied is not None and last_applied.date() == today


def run_weekly_progression(session: Session, user_id: str, *,
                            today: date | None = None) -> list[ProgressionHistory]:
    today = today or today_ist()
    # FOR UPDATE: found live (code audit) — nothing serialized two concurrent
    # runs touching the same user's rows (e.g. a slow daily run still
    # finishing when the next day's trigger fires, or this batch job racing
    # a chat-confirmed apply_escalation call on the same entry). This blocks
    # a second writer until the first's transaction commits, instead of both
    # reading the same starting point and one silently overwriting the
    # other's result.
    entries = session.scalars(
        select(UserProgram).where(
            UserProgram.user_id == user_id,
            UserProgram.status == "active",       # 15.4 — never progress a suspended entry
            UserProgram.source != "user_override",  # 15.2 — never progressed
        ).with_for_update()
    ).all()

    written: list[ProgressionHistory] = []
    for entry in entries:
        taxonomy = session.get(ActivityTaxonomy, entry.activity_type)
        if taxonomy is None:
            continue
        if _already_progressed_today(session, user_id, entry.activity_type, today):
            continue

        old_target = float(entry.target_amount)
        reps_ceiling = None
        if taxonomy.prescription_type == "reps":
            reps_ceiling = _reps_cycle_ceiling(taxonomy, entry)
        old_volume, floor_volume, ceiling_volume = _volume_bounds(
            taxonomy, entry, reps_ceiling_amount=reps_ceiling)

        week = _week_number(entry.added_at, today)
        k = float(taxonomy.curve_k) if taxonomy.curve_k is not None else DEFAULT_CURVE_K
        curve_pct = compute_curve_increase(old_volume, week, k)
        adherence_pct = _window_adherence(session, user_id, entry.activity_type,
                                           old_volume, today)

        # 15.3 rule table (the discomfort-hold row is not reachable — see module
        # docstring) applied to arrive at a raw (pre-guard) percentage change.
        if adherence_pct >= 0.80:
            raw_pct = curve_pct
            reason = "curve"
        elif adherence_pct >= 0.50:
            raw_pct = 0.0
            reason = "hold"
        else:
            raw_pct = -REDUCE_PCT
            reason = "reduce"

        # Found live (code audit): this automated batch job never checked the
        # condition safety grid before increasing a target — only the
        # on-demand chat escalation path did (app/progression/analysis.py's
        # _condition_gate). If a user's conditions change after an activity
        # is already active, or a reviewer later marks it "avoid" for a
        # condition they have, this job would keep raising volume with zero
        # safety awareness — the one write path here that wasn't chat-gated.
        # Mirrors the chat path's own behavior on an unsafe verdict: don't
        # apply the increase, hold instead. Only checked when an increase is
        # actually on the table — never for "reduce", which is always safe.
        if reason == "curve" and not _is_safe_to_progress(session, user_id, entry.activity_type):
            raw_pct = 0.0
            reason = "hold"

        if taxonomy.prescription_type == "reps" and reason == "curve":
            # Reps-only fast track (see _reps_curve_step) replaces the generic
            # pct-based guard chain below entirely: average-driven curve,
            # fixed two-stage ceiling, and its own ceiling-crossing bump —
            # only in the curve branch, so "hold"/"reduce" are untouched.
            new_volume, bumped, raw_volume = _reps_curve_step(session, user_id, taxonomy, entry, today)
            reason = "double_progression" if bumped else "curve"
            raw_pct = (raw_volume / old_volume - 1) if old_volume else 0.0
            curve_pct = raw_pct
        else:
            # 15.4 guard chain — tightest-relevant-one-wins, same ordering as
            # the RLM design doc §6 (minus the on-demand-only 1.5x escalation
            # guard, which only applies to Module 16's proposal path, not
            # this batch job).
            guarded_pct = max(-MAX_ADJUSTMENT_PCT, min(MAX_ADJUSTMENT_PCT, raw_pct))
            new_volume = old_volume * (1 + guarded_pct)

            if new_volume <= floor_volume:
                new_volume = floor_volume
                if reason == "reduce":
                    reason = "floor"
            elif new_volume > ceiling_volume:
                new_volume = ceiling_volume

        _log_if_clamped(
            path="weekly_progression", user_id=user_id, activity_type=entry.activity_type,
            requested_pct=raw_pct, applied_pct=(new_volume / old_volume - 1) if old_volume else 0.0,
        )
        _apply_new_volume(entry, taxonomy, new_volume)

        # Checked AFTER snapping to a real progression_step, not the raw
        # pre-snap volume: a small curve/reduce request can round back to the
        # same prescribable amount (e.g. a 10% bump on a 2-rep-step exercise
        # isn't yet enough to cross into the next real step) — that is
        # genuinely "hold", even though the underlying math wanted a change.
        # "double_progression" is exempt too — it's a genuine set-count
        # change even on the rare occasion the per-set DISPLAYED amount
        # happens to coincide with the old one.
        if float(entry.target_amount) == old_target and reason not in ("floor", "double_progression"):
            reason = "hold"

        written.append(ProgressionHistory(
            user_id=user_id, activity_type=entry.activity_type,
            old_target=Decimal(str(round(old_target, 2))),
            new_target=entry.target_amount,
            adherence_pct=Decimal(str(round(adherence_pct * 100, 2))),
            curve_pct=Decimal(str(round(_clamp_for_history(curve_pct), 2))),
            reason=reason,
        ))
        session.add(written[-1])

    session.flush()
    return written


# --- Phase 6: dashboard percentage graph (design doc §7) -------------------

DEFAULT_SERIES_WEEKS = 12  # matches the trailing-window sizes used elsewhere in
# this module (ADHERENCE_WINDOW_DAYS=7, analysis.py's 4/8-week checks) — long
# enough to see the curve's early-steep/later-flat shape, short enough that a
# years-old account doesn't hand the frontend an ever-growing payload.


def progression_series(session: Session, user_id: str, *,
                        weeks: int = DEFAULT_SERIES_WEEKS) -> list[dict]:
    """Design doc §7 — per-activity weekly-increase history for the dashboard
    graph. Purely additive/read-only: reshapes what run_weekly_progression and
    apply_escalation already recorded, writes nothing. `curve_pct` is the
    diminishing curve's raw output before guard clamping (or the confirmed
    escalation's own pct, for an "escalation"-reason row); the actually-applied
    change is old_target -> new_target on the same point, so a chart can show
    both the trend line and what the guards did to it if it wants to."""
    rows = session.scalars(
        select(ProgressionHistory)
        .where(ProgressionHistory.user_id == user_id)
        .order_by(ProgressionHistory.applied_at.asc())
    ).all()

    by_activity: dict[str, list[ProgressionHistory]] = {}
    for r in rows:
        by_activity.setdefault(r.activity_type, []).append(r)

    series = []
    for activity_type, history in by_activity.items():
        taxonomy = session.get(ActivityTaxonomy, activity_type)
        display_name = taxonomy.display_name if taxonomy else activity_type
        points = [
            {
                "applied_at": h.applied_at.isoformat(),
                "curve_pct": float(h.curve_pct),
                "adherence_pct": float(h.adherence_pct),
                "old_target": float(h.old_target),
                "new_target": float(h.new_target),
                "reason": h.reason,
            }
            for h in history[-weeks:]
        ]
        series.append({
            "activity_type": activity_type, "display_name": display_name, "points": points,
        })
    return sorted(series, key=lambda s: s["display_name"])


# --- Phase 5: chat-confirmed escalation write path (design doc §6) ---------

def apply_escalation(session: Session, user_id: str, activity_type: str,
                      proposed_pct_increase: float, *,
                      adherence_pct_snapshot: float | None = None) -> ProgressionHistory:
    """Writes a chat-confirmed escalation proposal through the EXACT SAME guard
    bounds as the weekly job above (_volume_bounds), so the design doc §6
    guards are one more independent clamp in a shared write path rather than a
    parallel path that could drift from Module 15's. Never trusts the caller's
    pct alone — re-clamps against every guard here too, since this must be
    safe to call with any float, not just the well-behaved output of
    app.progression.analysis._pick_escalation_step.

    The confirmation gate itself (16.5 — nothing here happens without an
    explicit yes) and the re-eligibility check at write time (16.3's
    principle: re-verify, don't trust a possibly-stale proposal) both live in
    the caller (app/rag/service.py), not this function.
    """
    from app.progression.analysis import ESCALATION_GUARD_PCT  # local: avoids a
    # module-level import cycle risk if analysis.py ever needs service.py later.

    # FOR UPDATE via select(), not session.get() (found live, second-pass
    # code audit): under Postgres READ COMMITTED, a FOR UPDATE lock does NOT
    # block a plain unlocked read from another transaction — only another
    # FOR UPDATE/write. run_weekly_progression's own row lock (see its own
    # comment) does nothing to protect THIS write path from racing it (or
    # from racing a second concurrent escalation call on the same entry):
    # both could read the same stale old_target, and whichever UPDATE
    # commits second silently overwrites the other's change with a
    # calculation based on outdated state. Locking here closes that gap
    # symmetrically.
    entry = session.scalar(
        select(UserProgram)
        .where(UserProgram.user_id == user_id, UserProgram.activity_type == activity_type)
        .with_for_update()
    )
    if entry is None or entry.status != "active" or entry.source == "user_override":
        raise NotFound(f"No active, escalatable program entry for {activity_type}")
    taxonomy = session.get(ActivityTaxonomy, activity_type)
    if taxonomy is None:
        raise NotFound(f"Unknown activity: {activity_type}")

    old_target = float(entry.target_amount)
    sides = _sides(taxonomy)
    today = today_ist()
    reps_ceiling = None
    if taxonomy.prescription_type == "reps":
        reps_ceiling = _reps_cycle_ceiling(taxonomy, entry)
    old_volume, floor_volume, ceiling_volume = _volume_bounds(
        taxonomy, entry, reps_ceiling_amount=reps_ceiling)

    # Independent guards, tightest wins — design doc §6's ordering. Every
    # ESCALATION_STEP_CHOICES value is already far under MAX_ADJUSTMENT_PCT
    # and ESCALATION_GUARD_PCT, so in normal operation neither should be the
    # one actually doing the clamping — they're the backstop, not the plan.
    guarded_pct = max(0.0, min(proposed_pct_increase, MAX_ADJUSTMENT_PCT, ESCALATION_GUARD_PCT))
    new_volume = old_volume * (1 + guarded_pct)
    reason = "escalation"
    if new_volume > ceiling_volume:
        # Same reps-only bump rule as the weekly job (_reps_curve_step): the
        # bump is earned by REAL behavior crossing the ceiling, not by the
        # proposed escalation pct alone pushing past it — so this checks the
        # actual trailing average, not just where guarded_pct landed.
        avg = _reps_trailing_average(session, user_id, activity_type, today) \
            if reps_ceiling is not None else None
        if avg is not None and avg > reps_ceiling and entry.target_sets < REPS_MAX_SETS:
            old_sets = entry.target_sets
            entry.target_sets = old_sets + 1
            # Same fix as _reps_curve_step: never redistribute above
            # REPS_HARD_CEILING (the ceiling of the cycle being entered,
            # not reps_ceiling which is the one just crossed), regardless of
            # how extreme the real average is.
            new_per_set = min((avg * old_sets) / entry.target_sets, REPS_HARD_CEILING)
            new_volume = max(new_per_set * entry.target_sets * sides, old_volume)
            reason = "double_progression"
        else:
            new_volume = ceiling_volume
    new_volume = max(new_volume, floor_volume)  # can't matter for a positive-only
    # escalation, kept for symmetry with the weekly job's own clamp shape.

    _log_if_clamped(
        path="escalation", user_id=user_id, activity_type=activity_type,
        requested_pct=proposed_pct_increase,
        applied_pct=(new_volume / old_volume - 1) if old_volume else 0.0,
    )
    _apply_new_volume(entry, taxonomy, new_volume)

    row = ProgressionHistory(
        user_id=user_id, activity_type=activity_type,
        old_target=Decimal(str(round(old_target, 2))), new_target=entry.target_amount,
        # Not a weekly adherence WINDOW the way the batch job computes one —
        # this is whatever adherence_trend value the caller's analyze_performance
        # findings actually showed at confirmation time, so "why did this change"
        # (15.6) stays honest instead of showing a placeholder zero.
        adherence_pct=Decimal(str(round(adherence_pct_snapshot or 0.0, 2))),
        curve_pct=Decimal(str(round(_clamp_for_history(proposed_pct_increase), 2))),
        reason=reason,
    )
    session.add(row)
    session.flush()
    return row
