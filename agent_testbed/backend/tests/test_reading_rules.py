"""Rules by BP reading (step 4, decided 2026-10-28): the latest reading within
90 days, the stricter of systolic and diastolic, bands that add up; a patient
with BP and no recent reading is treated as 140/90. AI and rules drafts never
hold a ruled-out exercise; the doctor only gets a warning."""
from datetime import date

import pytest
from sqlalchemy import select

from agent.draft import AIDraft, AIPick, build_draft
from store import plans
from store.models import Exercise
from store.seed import EXERCISE_PROPERTIES

TODAY = date(2026, 10, 28)
PATIENT = {"age": 50, "sex": "F", "bmi": 24.0}


def bp(sys_, dia, day="2026-10-20"):
    return {"sys": float(sys_), "dia": float(dia), "date": day}


def allowed(db, reading, codes=("bp_controlled",)):
    out, lines = plans.candidates(db, list(codes), PATIENT["age"], PATIENT["bmi"], reading)
    return {e["activity_type"] for e in out}, lines


# ── Which reading counts ────────────────────────────────────────────────────

def test_latest_bp_takes_the_newest_reading():
    vitals = [{"date": date(2026, 10, 20), "bp": "150/95", "bp_sys": 150.0, "bp_dia": 95.0},
              {"date": date(2026, 9, 1), "bp_sys": 120.0, "bp_dia": 80.0}]
    assert plans.latest_bp(vitals, TODAY) == bp(150, 95)


def test_latest_bp_reads_the_text_when_the_numbers_are_missing():
    assert plans.latest_bp([{"date": "2026-10-20", "bp": "142 / 88"}], TODAY) == bp(142, 88)


def test_latest_bp_skips_visits_without_bp():
    vitals = [{"date": date(2026, 10, 25), "pulse": 80}, {"date": date(2026, 10, 20), "bp_sys": 130, "bp_dia": 85}]
    assert plans.latest_bp(vitals, TODAY) == bp(130, 85)


def test_reading_older_than_90_days_doesnt_count():
    assert plans.latest_bp([{"date": date(2026, 7, 1), "bp_sys": 150, "bp_dia": 95}], TODAY) is None
    assert plans.latest_bp([], TODAY) is None


# ── The bands ───────────────────────────────────────────────────────────────

def test_below_140_90_nothing_extra(db):
    with_bp, _ = allowed(db, bp(130, 85))
    without, _ = allowed(db, bp(110, 70))
    assert with_bp == without and {"wall_sit", "neck_isometric"} <= with_bp


@pytest.mark.parametrize("reading", [bp(150, 85), bp(135, 95)])  # systolic or diastolic: the stricter counts
def test_140_band_leaves_out_holds_and_vigorous(db, reading):
    kinds, lines = allowed(db, reading)
    assert not kinds & {"wall_sit", "neck_isometric", "running"}
    assert {"walk", "march_in_place", "sit_to_stand", "slow_breathing"} <= kinds
    assert any("Wall Sit" in line and "Neck Hold" in line for line in lines)


def test_160_band_only_walking_breathing_mobility(db):
    kinds, _ = allowed(db, bp(165, 95))
    by_type = {e.activity_type: e for e in db.scalars(select(Exercise))}
    assert kinds and all(by_type[k].exercise_type in ("aerobic", "breathing", "mobility") for k in kinds)
    assert all(by_type[k].intensity != "vigorous" for k in kinds)
    assert {"walk", "march_in_place", "slow_breathing"} <= kinds and "sit_to_stand" not in kinds


def test_180_band_no_exercise_plan(db):
    kinds, lines = allowed(db, bp(185, 100))
    assert kinds == set() and any("180/110 or above" in line for line in lines)


def test_no_recent_reading_with_bp_is_treated_as_140_90(db):
    kinds, lines = allowed(db, None)
    assert "wall_sit" not in kinds and any("no reading in the last 90 days" in line for line in lines)


def test_no_reading_without_bp_changes_nothing(db):
    kinds, lines = allowed(db, None, codes=("arthritis_knee",))
    assert "wall_sit" in kinds and lines == []


def test_a_reading_applies_even_without_a_bp_diagnosis(db):
    kinds, _ = allowed(db, bp(150, 95), codes=("arthritis_knee",))
    assert "wall_sit" not in kinds


# ── Drafts and the doctor ───────────────────────────────────────────────────

def assessment(codes, reading):
    return {"id": "a1", "codes": codes, "severity": "moderate", "severe_reasons": [], "problem": "", "body_area": "",
            "concerns": [], "conditions": [], "readings": {"bp": reading}}


def ai_picking(*kinds):
    def ask(*_):
        return AIDraft(exercises=[AIPick(activity_type=k, why="helps") for k in kinds],
                       instructions="Go slowly.", reason="Gentle start.")
    return ask


def test_ai_offered_only_what_the_reading_allows(db):
    seen = {}

    def ask(_a, _p, offered):
        seen["kinds"] = {e["activity_type"] for e in offered}
        return AIDraft(exercises=[AIPick(activity_type="walk", why="x")], instructions="Go slowly.", reason="r")
    p = build_draft(db, "p1", assessment(["bp_controlled"], bp(150, 95)), PATIENT, ask_ai=ask)
    assert "wall_sit" not in seen["kinds"] and p.source == "ai"
    assert "Wall Sit" in p.reason  # the draft says what the BP left out


def test_ai_picking_a_ruled_out_exercise_falls_back_to_rules(db):
    p = build_draft(db, "p1", assessment(["bp_controlled"], bp(150, 95)), PATIENT,
                    ask_ai=ai_picking("walk", "wall_sit"))
    assert p.source == "rules" and "wall_sit" not in [e["activity_type"] for e in p.exercises]


def test_180_band_draft_goes_to_the_doctor(db):
    p = build_draft(db, "p1", assessment(["bp_controlled"], bp(185, 112)), PATIENT, ask_ai=ai_picking("walk"))
    assert (p.source, p.exercises) == ("doctor", []) and "180/110 or above" in p.reason


def test_rules_check_flags_a_ruled_out_exercise(db):
    problems = plans.violations(db, [{"activity_type": "wall_sit", "sets": 2, "amount": 20}], ["bp_controlled"],
                                bp(150, 95))
    assert any("Wall Sit" in x for x in problems)


def test_doctor_gets_a_warning_not_a_block(db):
    warnings = plans.doctor_warnings(db, [{"activity_type": "wall_sit", "sets": 2, "amount": 20}],
                                     ["bp_controlled"], bp(150, 95))
    assert any(w.startswith("Not advised") and "150/95" in w for w in warnings["wall_sit"])
    catalog = {e["activity_type"]: e for e in plans.exercise_catalog(db, ["bp_controlled"], bp(150, 95))}
    assert catalog["wall_sit"]["verdict"] == "not advised" and catalog["walk"]["verdict"] == "safe"
    assert plans.doctor_exercises(db, [{"activity_type": "wall_sit", "sets": 2, "amount": 20}])  # still allowed


# ── Exercise properties ─────────────────────────────────────────────────────

def test_every_exercise_has_valid_properties(db):
    for e in db.scalars(select(Exercise)):
        for field, values in EXERCISE_PROPERTIES.items():
            assert getattr(e, field) in values, (e.activity_type, field)
    holds = {e.activity_type for e in db.scalars(select(Exercise).where(Exercise.breath_hold))}
    assert {"wall_sit", "neck_isometric", "glute_bridge", "dead_bug"} <= holds
