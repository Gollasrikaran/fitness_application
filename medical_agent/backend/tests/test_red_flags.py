import pytest

from app.agent.red_flags import scan


def codes(text):
    return [f.code for f in scan(text)]


@pytest.mark.parametrize("text,code", [
    ("I have chest pain since morning", "chest_pain"),
    ("mujhe seene mein dard ho raha hai", "chest_pain"),
    ("मुझे सीने में दर्द हो रहा है", "chest_pain"),
    ("I can't breathe properly after walking", "breathing"),
    ("saans nahi aa rahi", "breathing"),             # the "nahi" IS the symptom
    ("I fainted in the bathroom", "fainting"),
    ("my face is drooping on one side", "stroke_signs"),
    ("I lost control of my bladder and my back hurts", "bladder_bowel"),
    ("numbness in my groin", "bladder_bowel"),
    ("I want to die", "self_harm"),
    ("jeena nahi chahta", "self_harm"),
    ("not sure why but chest pain started today", "chest_pain"),  # contrast resets negation
])
def test_emergency_flags(text, code):
    flags = scan(text)
    assert code in [f.code for f in flags]
    assert flags[0].level == "emergency"


@pytest.mark.parametrize("text", [
    "no chest pain, just a sore lower back",
    "I don't have chest pain",
    "seene mein dard nahi hai, kamar mein hai",
    "my hamstrings feel tight after the stretch",
    "kamar mein halka dard hai",
])
def test_no_emergency(text):
    assert not [f for f in scan(text) if f.level == "emergency"]


@pytest.mark.parametrize("text,code", [
    ("I can't put weight on my left leg", "cant_bear_weight"),
    ("the pain wakes me up at night", "night_pain"),
    ("knee is swollen and hot", "hot_swollen"),
    ("bukhar bhi hai", "fever"),
    ("can I take paracetamol for this?", "medication"),
])
def test_priority_flags(text, code):
    assert code in codes(text)
