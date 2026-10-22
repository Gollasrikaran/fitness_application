"""Clinic record -> our condition codes (the codes the exercise safety grid uses).

Fixed rules, no AI. Sources, most trusted first: conditions a doctor recorded,
the health-history questionnaire, then keywords in recent diagnoses. BP and
sugar are "controlled" unless a recent vital flag says otherwise.

PROVISIONAL: built by the product team so we can test. A clinician should
review every row before real use, as with the safety grid.
"""
from __future__ import annotations

import re

# Doctor-recorded long-term conditions (long_term_condition.name).
RECORDED = {
    "Hypertension": "bp",
    "Diabetes Mellitus": "diabetes",
    "Heart Failure": "heart_condition",
    "Coronary Artery Disease": "heart_condition",
    "Stroke / CVA": "neurological",
    "Epilepsy": "neurological",
    "Depression": "depression",
    "Anxiety Disorder": "anxiety",
    # Serious illness with no exercise rules of ours: a doctor decides.
    "Chronic Kidney Disease": "other_unlisted",
    "COPD": "other_unlisted",
    "Cancer": "other_unlisted",
    "HIV/AIDS": "other_unlisted",
    "Tuberculosis": "other_unlisted",
    "Chronic Hepatitis": "other_unlisted",
    "Schizophrenia": "other_unlisted",
}

# Health-history questionnaire items marked "present".
HISTORY = {
    "hypertension": "bp",
    "diabetes": "diabetes",
    "heart_disease": "heart_condition",
    "high_cholesterol": "high_cholesterol",
    "tuberculosis": "other_unlisted",
}

# Keywords in recent diagnoses (doctors' shorthand), checked in order.
DIAGNOSIS = [
    (r"\b(htn|hypertension|high bp)\b", "bp"),
    (r"\b(t2dm|dm|diabetes|diabetic)\b", "diabetes"),
    (r"\b(cad|ihd|heart failure|angina|myocardial)\b", "heart_condition"),
    (r"\b(cva|stroke|epilepsy|seizure|neuropathy)\b", "neurological"),
    (r"\bknee\b", "arthritis_knee"),
    (r"\b(lbp|low back|lower back|back ?ache|back pain|lumbar)\b", "chronic_back_pain"),
    (r"\b(pivd|disc prolapse|slip disc|herniat)", "herniated_disk"),
    (r"\b(cervical|spondylosis|neck pain)\b", "spondylosis"),
    (r"\b(hip)\b", "arthritis_hip"),
    (r"\b(sprain|strain)\b", "sprain_strain"),
    (r"\b(gout|hyperuricemia|uric)\b", "gout"),
    (r"\b(pcod|pcos)\b", "pcos"),
    (r"\b(dyslipid|cholesterol)", "high_cholesterol"),
    (r"\b(obesity|obese)\b", "obesity"),
    (r"\b(pregnan|anc|primi|gravida)", "pregnancy"),
    (r"\b(depression|depressive)\b", "depression"),
    (r"\b(anxiety)\b", "anxiety"),
]

OBESE_BMI = 30
_BP_UNCONTROLLED = re.compile(r"^BP_(SYS|DIA)_(HIGH|CRITICAL)$")
_SUGAR_UNCONTROLLED = re.compile(r"SUGAR")


def map_conditions(context: dict) -> tuple[list[str], list[str]]:
    """Return (condition codes, one evidence line per code)."""
    found: dict[str, str] = {}

    def add(code: str, why: str) -> None:
        found.setdefault(code, why)

    conds = context["conditions"]
    for c in conds["doctor_recorded"]:
        if c["name"] in RECORDED:
            add(RECORDED[c["name"]], f"doctor recorded: {c['name']}")
    for h in conds["health_history"]:
        if h["item"] in HISTORY:
            add(HISTORY[h["item"]], f"health history: {h['item']}")
    for d in conds["recent_diagnoses"]:
        text = f"{d.get('confirmed') or ''} {d.get('provisional') or ''}".lower()
        for pattern, code in DIAGNOSIS:
            if re.search(pattern, text):
                add(code, f"diagnosis {d['date']}: {text.strip()}")
    bmi = context["body"].get("bmi")
    if bmi and bmi >= OBESE_BMI:
        add("obesity", f"BMI {bmi}")

    # Controlled or not, from the recent vital flags.
    codes = {f["code"] for f in context["vital_flags"]}
    if "bp" in found:
        why = found.pop("bp")
        bad = sorted(c for c in codes if _BP_UNCONTROLLED.match(c))
        if bad:
            add("high_bp", f"{why}; recent {', '.join(bad)}")
        else:
            add("bp_controlled", f"{why}; no high BP flag recently")
    if "diabetes" in found:
        why = found.pop("diabetes")
        bad = sorted(c for c in codes if _SUGAR_UNCONTROLLED.search(c))
        if bad:
            add("diabetes", f"{why}; recent {', '.join(bad)}")
        else:
            add("diabetes_controlled", f"{why}; no sugar flag recently")

    codes_out = sorted(found) or ["none"]
    return codes_out, [f"{code}: {found[code]}" for code in sorted(found)]


# Our conditions that always need a doctor (the "refer" bucket).
REFER = {"diabetes", "high_bp", "heart_condition", "pregnancy", "recent_surgery", "acute_injury",
         "neurological", "other_unlisted"}
