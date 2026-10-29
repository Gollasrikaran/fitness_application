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
    out, lines = plans.candidates(db, list(codes), PATIENT["age"], PATIENT["bmi"], {"bp": reading})
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


def test_160_band_only_walking_balance_breathing_mobility(db):
    kinds, _ = allowed(db, bp(165, 95))
    by_type = {e.activity_type: e for e in db.scalars(select(Exercise))}
    assert kinds and all(by_type[k].exercise_type in ("aerobic", "balance", "breathing", "mobility") for k in kinds)
    assert all(by_type[k].intensity != "vigorous" for k in kinds)
    assert {"walk", "march_in_place", "slow_breathing", "single_leg_stand"} <= kinds and "sit_to_stand" not in kinds


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
                                {"bp": bp(150, 95)})
    assert any("Wall Sit" in x for x in problems)


def test_doctor_gets_a_warning_not_a_block(db):
    warnings = plans.doctor_warnings(db, [{"activity_type": "wall_sit", "sets": 2, "amount": 20}],
                                     ["bp_controlled"], {"bp": bp(150, 95)})
    assert any(w.startswith("Not advised") and "150/95" in w for w in warnings["wall_sit"])
    catalog = {e["activity_type"]: e for e in plans.exercise_catalog(db, ["bp_controlled"], {"bp": bp(150, 95)})}
    assert catalog["wall_sit"]["verdict"] == "not advised" and catalog["walk"]["verdict"] == "safe"
    assert plans.doctor_exercises(db, [{"activity_type": "wall_sit", "sets": 2, "amount": 20}])  # still allowed


# ── Exercise properties ─────────────────────────────────────────────────────

def test_every_exercise_has_valid_properties(db):
    for e in db.scalars(select(Exercise)):
        for field, values in EXERCISE_PROPERTIES.items():
            assert getattr(e, field) in values, (e.activity_type, field)
    holds = {e.activity_type for e in db.scalars(select(Exercise).where(Exercise.breath_hold))}
    assert {"wall_sit", "neck_isometric", "glute_bridge", "dead_bug"} <= holds


# ── Sugar, Hb, SpO2, resting pulse (added 2026-10-28) ───────────────────────

def one(value, day="2026-10-20"):
    return {"value": float(value), "date": day}


def sugar(high, low=None, day="2026-10-20"):
    return {"high": float(high), "low": float(low if low is not None else high), "date": day}


def allowed_with(db, readings, codes=("arthritis_knee",)):
    out, lines = plans.candidates(db, list(codes), PATIENT["age"], PATIENT["bmi"], readings)
    return {e["activity_type"] for e in out}, lines


def test_latest_readings_reads_every_metric():
    vitals = [{"date": date(2026, 10, 20), "bp": "130/85", "fasting_sugar_mg_dl": 110, "nonfasting_sugar_mg_dl": "260",
               "hb": 11.2, "spo2": 97, "pulse": 88},
              {"date": date(2026, 9, 1), "hb": 7.0}]
    assert plans.latest_readings(vitals, TODAY) == {
        "bp": bp(130, 85), "sugar": sugar(260, 110), "hb": one(11.2), "spo2": one(97), "pulse": one(88)}


def test_latest_readings_skip_typing_errors_and_old_visits():
    vitals = [{"date": date(2026, 10, 20), "spo2": 970, "pulse": 0},
              {"date": date(2026, 10, 1), "spo2": 96},
              {"date": date(2026, 6, 1), "pulse": 70, "hb": 9}]
    out = plans.latest_readings(vitals, TODAY)
    assert out["spo2"] == one(96, "2026-10-01") and out["pulse"] is None and out["hb"] is None


def test_normal_readings_change_nothing(db):
    normal = {"sugar": sugar(140, 95), "hb": one(13), "spo2": one(98), "pulse": one(75)}
    assert allowed_with(db, normal) == allowed_with(db, {})


@pytest.mark.parametrize("readings", [
    {"sugar": sugar(260)}, {"hb": one(9.5)}, {"spo2": one(93)}, {"pulse": one(105)}, {"pulse": one(45)}])
def test_borderline_readings_leave_out_vigorous_only(db, readings):
    kinds, lines = allowed_with(db, readings, codes=("none",))
    every, _ = allowed_with(db, {}, codes=("none",))
    assert "running" in every and every - kinds == {"running"} and len(lines) == 1


@pytest.mark.parametrize("readings, words", [
    ({"sugar": sugar(320)}, "300 mg/dL or above"), ({"sugar": sugar(180, 62)}, "low sugar"),
    ({"hb": one(7.4)}, "below 8 g/dL"), ({"spo2": one(90)}, "below 92%"),
    ({"pulse": one(125)}, "120/min or above"), ({"pulse": one(38)}, "below 40/min")])
def test_dangerous_readings_mean_no_plan(db, readings, words):
    kinds, lines = allowed_with(db, readings)
    assert kinds == set() and any(words in line for line in lines)


def test_rules_from_several_readings_add_up(db):
    readings = {"bp": bp(150, 95), "hb": one(9)}
    kinds, _ = allowed_with(db, readings, codes=("none",))
    assert not kinds & {"wall_sit", "neck_isometric", "running"}
    _, lines = plans.reading_limits(db, ["none"], readings)
    assert len(lines) == 3 and any("Hb 9 g/dL" in line for line in lines)


def test_sugar_draft_goes_to_the_doctor_and_says_why(db):
    a = assessment(["diabetes_controlled"], None)
    a["readings"] = {"bp": None, "sugar": sugar(340)}
    p = build_draft(db, "p1", a, PATIENT, ask_ai=ai_picking("walk"))
    assert (p.source, p.exercises) == ("doctor", []) and "340 mg/dL on 2026-10-20" in p.reason


def test_doctor_sees_the_reading_in_the_warning(db):
    w = plans.doctor_warnings(db, [{"activity_type": "running", "sets": 1, "amount": 1}], ["none"],
                              {"pulse": one(110)})
    assert any("110/min" in x for x in w["running"])


def test_every_rule_in_the_csv_loads():
    from store.seed import _rows, reading_rules
    assert len(reading_rules()) == len(list(_rows("reading_rules.csv")))


@pytest.mark.parametrize("when, metric", [("sys>=140 or high>=250", "bp"), ("value=>10", "hb"), ("value<", "spo2"),
                                          ("value<10", "ldl")])
def test_bad_conditions_are_refused(when, metric):
    from store.seed import parse_when
    with pytest.raises(ValueError):
        parse_when(when, metric)
