"""Pure-logic tests for the RLM recursive analysis agent (design doc §5.3) —
no DB, no real LLM call. _pick_escalation_step's one LLM call is stubbed via
monkeypatch where eligibility tests need it; _snap_to_step_choice (the parsing
half) is tested directly since it never touches the network at all.
"""
from app.progression import analysis
from app.progression.analysis import (
    ESCALATION_DEFAULT_STEP, ESCALATION_GUARD_PCT, ESCALATION_STEP_CHOICES,
    _check_discomfort, _escalation_proposal, _snap_to_step_choice, _summary_signal,
)


def test_discomfort_is_honest_about_not_being_tracked():
    """Module 14.6 doesn't exist — this must never claim 'no discomfort found',
    only that discomfort isn't tracked yet. A false all-clear would read as a
    real safety signal that doesn't exist."""
    finding = _check_discomfort("glute_bridge")
    assert finding["available"] is False
    assert "not tracked" in finding["note"]


def test_plateau_overrides_everything_else_in_summary():
    adherence = {"value": 95, "trend": "improving"}
    plateau = {"detected": True}
    assert _summary_signal(adherence, plateau) == "plateaued"


def test_declining_trend_is_behind():
    adherence = {"value": 70, "trend": "declining"}
    plateau = {"detected": False}
    assert _summary_signal(adherence, plateau) == "behind"


def test_low_value_is_behind_even_without_a_trend_label():
    adherence = {"value": 30, "trend": None}
    plateau = {"detected": False}
    assert _summary_signal(adherence, plateau) == "behind"


def test_high_value_is_ahead_of_plan():
    adherence = {"value": 120, "trend": "steady"}
    plateau = {"detected": False}
    assert _summary_signal(adherence, plateau) == "ahead_of_plan"


def test_no_history_defaults_to_on_track():
    assert _summary_signal({}, {"detected": False}) == "on_track"


def test_ordinary_adherence_is_on_track():
    adherence = {"value": 85, "trend": "steady"}
    plateau = {"detected": False}
    assert _summary_signal(adherence, plateau) == "on_track"


# --- _snap_to_step_choice: pure parsing, no LLM, no monkeypatch needed -----

def test_snap_parses_plain_decimal():
    assert _snap_to_step_choice("0.10") == 0.10


def test_snap_parses_bare_percent_as_a_fraction():
    """The model might reply "10" or "15" meaning percent, not the fraction
    0.10/0.15 the prompt actually asked for — must still land correctly."""
    assert _snap_to_step_choice("10") == 0.10
    assert _snap_to_step_choice("15%") == 0.15


def test_snap_never_returns_a_value_outside_the_fixed_choices():
    for reply in ["0.5", "1", "0.02", "50", "nonsense", ""]:
        assert _snap_to_step_choice(reply) in ESCALATION_STEP_CHOICES


def test_snap_falls_back_to_default_on_unparseable_reply():
    assert _snap_to_step_choice("I'm not sure") == ESCALATION_DEFAULT_STEP


def test_snap_prefers_closest_choice_not_first_match():
    # 0.12 is closer to 0.10 than to 0.15.
    assert _snap_to_step_choice("0.12") == 0.10
    # 0.135 is closer to 0.15 than to 0.10.
    assert _snap_to_step_choice("0.135") == 0.15


# --- _escalation_proposal: eligibility gating (LLM step-pick stubbed) ------

def _stub_step(monkeypatch, value):
    monkeypatch.setattr(analysis, "_pick_escalation_step", lambda adherence, api_key: value)


def test_escalation_not_eligible_when_condition_gate_unsafe(monkeypatch):
    _stub_step(monkeypatch, 0.05)
    adherence = {"value": 105, "trend": "improving", "window_weeks": 4}
    plateau = {"detected": False}
    gate = {"checked": True, "cached": False, "safe": False}
    assert _escalation_proposal(adherence, plateau, gate, api_key="x") == {"eligible": False}


def test_escalation_not_eligible_when_plateaued(monkeypatch):
    _stub_step(monkeypatch, 0.05)
    adherence = {"value": 105, "trend": "improving", "window_weeks": 4}
    plateau = {"detected": True}
    gate = {"checked": True, "cached": False, "safe": True}
    assert _escalation_proposal(adherence, plateau, gate, api_key="x")["eligible"] is False


def test_escalation_not_eligible_below_100_adherence(monkeypatch):
    """Raised from the earlier >=90 threshold: the user asked for the small
    step-based proposal to kick in only once someone has actually cleared
    100% adherence, not merely gotten close."""
    _stub_step(monkeypatch, 0.05)
    for value in (89, 95, 99):
        adherence = {"value": value, "trend": "steady", "window_weeks": 4}
        plateau = {"detected": False}
        gate = {"checked": True, "cached": False, "safe": True}
        assert _escalation_proposal(adherence, plateau, gate, api_key="x")["eligible"] is False


def test_escalation_not_eligible_when_declining_even_if_value_high(monkeypatch):
    """A high absolute value with a declining trend is not the same as being
    reliably ahead — trend guards against a one-good-week fluke."""
    _stub_step(monkeypatch, 0.05)
    adherence = {"value": 120, "trend": "declining", "window_weeks": 4}
    plateau = {"detected": False}
    gate = {"checked": True, "cached": False, "safe": True}
    assert _escalation_proposal(adherence, plateau, gate, api_key="x")["eligible"] is False


def test_escalation_eligible_at_exactly_100_uses_the_picked_step(monkeypatch):
    _stub_step(monkeypatch, 0.05)
    adherence = {"value": 100, "trend": "steady", "window_weeks": 4}
    plateau = {"detected": False}
    gate = {"checked": True, "cached": False, "safe": True}
    proposal = _escalation_proposal(adherence, plateau, gate, api_key="x")
    assert proposal["eligible"] is True
    assert proposal["proposed_pct_increase"] == 0.05


def test_escalation_eligible_never_exceeds_the_guard_even_if_step_picker_misbehaves(monkeypatch):
    """Belt-and-suspenders: even if _pick_escalation_step somehow returned
    something outside its own fixed choice set, the guard clamp still wins."""
    _stub_step(monkeypatch, 0.9)
    adherence = {"value": 150, "trend": "improving", "window_weeks": 4}
    plateau = {"detected": False}
    gate = {"checked": True, "cached": False, "safe": True}
    proposal = _escalation_proposal(adherence, plateau, gate, api_key="x")
    assert proposal["proposed_pct_increase"] <= ESCALATION_GUARD_PCT
    assert proposal["capped_at"] == ESCALATION_GUARD_PCT


def test_escalation_reason_never_claims_discomfort_was_checked(monkeypatch):
    """The design doc's own example reason string says 'no discomfort flags' —
    this codebase cannot honestly say that (14.6 isn't built), so the reason
    text must not imply discomfort was ruled out."""
    _stub_step(monkeypatch, 0.10)
    adherence = {"value": 130, "trend": "improving", "window_weeks": 4}
    plateau = {"detected": False}
    gate = {"checked": True, "cached": False, "safe": True}
    proposal = _escalation_proposal(adherence, plateau, gate, api_key="x")
    assert "no discomfort flags" not in proposal["reason"]
    assert "not yet tracked" in proposal["reason"]
