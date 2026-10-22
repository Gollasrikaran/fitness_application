"""Deterministic red-flag detection, run before the LLM on every message.

"emergency" flags skip the LLM entirely: the patient gets a fixed
seek-care-now message and an urgent case is opened. "priority" flags still
let the LLM reply, but the turn is forced to a doctor.

Patterns cover English, romanised Hindi (Hinglish) and Devanagari. They are
deliberately broad: a false alarm costs a doctor a minute, a miss can cost
much more. THIS LIST IS NOT CLINICALLY REVIEWED — a clinician should sign
it off before real patients use it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Flag:
    code: str
    label: str
    level: str  # emergency | priority


@dataclass(frozen=True)
class _Rule:
    flag: Flag
    pattern: re.Pattern
    # "dard nahi hai" negates "dard"; "saans nahi aa rahi" does NOT negate
    # "saans" — the "nahi" is the symptom. So Hindi post-negation is opt-in.
    hindi_negatable: bool = True


def _r(code, label, level, patterns, hindi_negatable=True):
    flag = Flag(code, label, level)
    return [_Rule(flag, re.compile(p, re.IGNORECASE), hindi_negatable) for p in patterns]


RULES: list[_Rule] = [
    *_r("chest_pain", "Chest pain or pressure", "emergency", [
        r"\bchest\s+(pain|pressure|tightness|tight|hurts?)", r"\bpain\s+in\s+(my\s+)?chest",
        r"\bsee?ne\s+(me|mein|main|mai)\s+(dard|dabav|dabaav|jakdan|jalan)",
        r"\bchhati\s+(me|mein|main)\s+dard", r"सीने\s*में\s*(दर्द|दबाव)", r"छाती\s*में\s*दर्द"]),
    *_r("breathing", "Trouble breathing", "emergency", [
        r"\b(can'?t|cannot|unable\s+to|difficulty|trouble|hard\s+to)\s+breath",
        r"\bshort(ness)?\s+of\s+breath", r"\bbreathless", r"\bsaa?ns\s+(nahi|nahin|nhi)\s+(aa|le)",
        r"\bsaa?ns\s+lene\s+(me|mein)\s+(dikkat|takleef|problem)", r"\bsaa?ns\s+phool",
        r"सांस\s*(नहीं|लेने\s*में)"], hindi_negatable=False),
    *_r("fainting", "Fainting or blacking out", "emergency", [
        r"\bfaint(ed|ing)?\b", r"\bpass(ed)?\s+out\b", r"\bblack(ed)?\s+out\b",
        r"\bbehosh", r"बेहोश"]),
    *_r("stroke_signs", "Possible stroke signs", "emergency", [
        r"\b(face|mouth)\s+(is\s+)?droop", r"\bslurred\s+speech", r"\bone\s+side\s+of\s+(my\s+)?(body|face)",
        r"\bsudden(ly)?\b.{0,30}\b(weak|numb|paralys)", r"\b(can'?t|cannot)\s+(speak|talk)\s+properly"]),
    *_r("bladder_bowel", "Loss of bladder/bowel control or groin numbness", "emergency", [
        r"\b(lost|loss\s+of|losing|can'?t|cannot)\s+(control\s+(of|over)\s+|control\s+)?(my\s+)?"
        r"(bladder|bowel|urine|pee|poop)",
        r"\bnumb(ness)?\s+(in|around)\s+(my\s+)?(groin|genitals?|private|saddle|inner\s+thighs?)",
        r"\bpeshab\s+(par\s+)?(control|kaabu|kabu)\s+(nahi|nahin|nhi)"], hindi_negatable=False),
    *_r("self_harm", "Thoughts of self-harm", "emergency", [
        r"\bsuicid", r"\bkill\s+myself", r"\bend\s+(my|it)\s+(life|all)", r"\bwant\s+to\s+die",
        r"\bself[\s-]?harm", r"\bhurt\s+myself", r"\bmarna\s+chaht[aie]",
        r"\bjeena\s+(nahi|nahin|nhi)\s+chaht[aie]", r"\bkhudkushi"], hindi_negatable=False),
    *_r("severe_trauma", "Serious injury", "emergency", [
        r"\b(fell|fall|accident|crash).{0,40}\b(can'?t\s+move|cannot\s+move|bone|bleeding)",
        r"\bbone\s+(is\s+)?(sticking|visible|poking)", r"\bheavy\s+bleeding", r"\bbahut\s+khoon"]),

    *_r("cant_bear_weight", "Can't put weight on a leg", "priority", [
        r"\b(can'?t|cannot|unable\s+to)\s+(put\s+weight|stand|walk)\b",
        r"\b(chal|khade?\s+ho)\s+(nahi|nahin|nhi)\s+(pa|paa|sak)"], hindi_negatable=False),
    *_r("night_pain", "Pain that wakes them at night", "priority", [
        r"\bpain\b.{0,30}\b(wakes?|woke)\s+me", r"\b(can'?t|cannot)\s+sleep\b.{0,30}\bpain",
        r"\braat\s+(ko|me|mein)\b.{0,20}\bdard"]),
    *_r("weight_loss", "Unexplained weight loss", "priority", [
        r"\b(losing|lost)\s+weight\s+without", r"\bunexplained\s+weight\s+loss",
        r"\bwajan\s+(apne\s+aap\s+)?kam\s+ho\s+raha"]),
    *_r("hot_swollen", "Hot, red or very swollen joint", "priority", [
        r"\b(swollen|swelling)\b.{0,30}\b(red|hot|warm)", r"\b(red|hot|warm)\b.{0,30}\b(swollen|swelling)",
        r"\bsoojan\b.{0,30}\b(laal|garam)"]),
    *_r("fever", "Fever", "priority", [r"\bfever\b", r"\bbukhar\b", r"\bbukhaar\b", r"बुखार"]),
    *_r("medication", "Question about medicines", "priority", [
        r"\b(medicine|medication|tablet|painkiller|dose|dosage|injection|steroid|ibuprofen|paracetamol|"
        r"diclofenac|combiflam|dolo)\b", r"\bdawai\b", r"\bdawa\b", r"दवा"]),
]

_EN_NEGATORS = {"no", "not", "never", "without", "dont", "don't", "didnt", "didn't", "havent",
                "haven't", "isnt", "isn't", "wasnt", "wasn't", "denies", "zero", "nor"}
_HI_NEGATORS = {"nahi", "nahin", "nhi", "na", "नहीं"}
# "not sure but chest pain" is NOT a negation: a contrast word resets it.
_CONTRAST = {"but", "however", "though", "although", "lekin", "magar", "par", "ab", "now"}


def _negated(text: str, start: int, end: int, hindi_negatable: bool) -> bool:
    before = re.findall(r"[\w']+", text[max(0, start - 40):start].lower())
    for i in range(len(before) - 1, -1, -1):
        if before[i] in _CONTRAST:
            before = before[i + 1:]
            break
    if any(w in _EN_NEGATORS for w in before[-3:]):
        return True
    if hindi_negatable:
        after = re.findall(r"[\w']+", text[end:end + 20].lower())[:2]
        if any(w in _HI_NEGATORS for w in after):
            return True
    return False


def scan(text: str) -> list[Flag]:
    """Flags present (and not negated) in the text, emergencies first."""
    found: dict[str, Flag] = {}
    for rule in RULES:
        if rule.flag.code in found:
            continue
        for m in rule.pattern.finditer(text):
            if not _negated(text, m.start(), m.end(), rule.hindi_negatable):
                found[rule.flag.code] = rule.flag
                break
    return sorted(found.values(), key=lambda f: f.level != "emergency")


EMERGENCY_REPLY = (
    "This could be serious, so please don't wait. Call 112 (or 108 for an ambulance) or go to the "
    "nearest emergency department now. Please stop exercising until a doctor has seen you. "
    "I've also flagged this to a doctor on our team as urgent."
)

SELF_HARM_REPLY = (
    "I'm really sorry you're going through this, and I'm glad you told me. You don't have to handle "
    "it alone. Please call Tele-MANAS on 14416 (free, 24x7, many Indian languages), or 112 if you "
    "might act on these thoughts right now. I've also let a doctor on our team know so someone can "
    "reach out to you."
)


def emergency_reply(flags: list[Flag]) -> str:
    return SELF_HARM_REPLY if any(f.code == "self_harm" for f in flags) else EMERGENCY_REPLY
