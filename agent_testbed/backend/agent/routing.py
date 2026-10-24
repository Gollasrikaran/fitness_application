"""Safety rules that decide, whatever the AI says. Plain code, no AI.

finalize() merges what the rules and the AI found and decides whether a
doctor must write the plan ("severe"). The rules can only escalate: the AI
can add conditions and raise the severity, never remove or lower them.
Which conditions need a doctor comes from the reference data (bucket
"refer"), not from code.
"""
from __future__ import annotations

import re

from agent.conditions import Finding, Reference, RuleResult

# The clinic's own vital flags (ELEVATED and LOW don't count as "not under control").
_BP_FLAG = re.compile(r"^BP_(SYS|DIA)_(HIGH|CRITICAL)$")
_SUGAR_FLAG = re.compile(r"SUGAR_MG_DL_(HIGH|CRITICAL)$")
_BP_KEYS = ("bp", "bp_sys", "bp_dia")
_SUGAR_KEYS = ("sugar_mg_dl", "fasting_sugar_mg_dl", "nonfasting_sugar_mg_dl")
# The AI reports BP and sugar as "controlled" by default; the vital flags decide.
_TO_MARKER = {"bp_controlled": "bp_any", "diabetes_controlled": "diabetes_any"}


def _uncontrolled(visits: list[dict], flags: list[dict], flag: re.Pattern, keys: tuple, what: str) -> tuple[bool, str]:
    """Not under control when the latest reading is flagged high, or any
    reading in the last 5 visits is critical. Returns (uncontrolled, why)."""
    critical = sorted({f"{f['code']} on {f['date']}" for f in flags
                       if flag.search(f["code"]) and f["severity"] == "CRITICAL"})
    if critical:
        return True, f"critical {what} reading: {', '.join(critical)}"
    latest = next((str(v["date"]) for v in visits if any(k in v.get("vitals", {}) for k in keys)), None)
    if latest is None:
        return False, f"no {what} reading in the recent visits"
    high = sorted({f["code"] for f in flags if flag.search(f["code"]) and str(f["date"]) == latest})
    if high:
        return True, f"latest {what} reading ({latest}) flagged {', '.join(high)}"
    return False, f"latest {what} reading ({latest}) not flagged high; nothing critical in the last 5 visits"


def _resolve_markers(findings: list[Finding], context: dict) -> list[tuple[str, str]]:
    """bp_any / diabetes_any -> controlled or not, from the clinic's vital
    flags. Returns (code, evidence line) per decision."""
    visits, flags = context["visits"], context["vital_flags"]
    notes = []
    for marker, strict, mild, flag, keys, what in (("bp_any", "high_bp", "bp_controlled", _BP_FLAG, _BP_KEYS, "BP"),
                                                   ("diabetes_any", "diabetes", "diabetes_controlled", _SUGAR_FLAG,
                                                    _SUGAR_KEYS, "sugar")):
        if not any(f.code in (marker, strict, mild) for f in findings):
            continue
        bad, why = _uncontrolled(visits, flags, flag, keys, what)
        for f in findings:
            if f.code == marker:
                f.code = strict if bad else mild
        notes.append((strict if bad else mild, why))
    return notes


def finalize(context: dict, ref: Reference, rules: RuleResult, ai: dict | None,
             ai_findings: list[Finding]) -> dict:
    findings = [*rules.findings, *ai_findings]
    for f in findings:
        f.code = _TO_MARKER.get(f.code, f.code)
    # A clinic condition we can't map: a doctor decides.
    findings += [Finding("other_unlisted", "rules", u, u) for u in rules.unmapped]
    flag_notes = _resolve_markers(findings, context)

    # The stricter reading wins: "controlled" evidence joins the uncontrolled
    # code, so the doctor still sees it (and the flags note below says why).
    codes = {f.code for f in findings}
    for strict, mild, flag_kind in (("high_bp", "bp_controlled", "BP"), ("diabetes", "diabetes_controlled", "sugar")):
        if strict in codes:
            for f in findings:
                if f.code == mild:
                    f.code = strict
            if any(code == mild for code, _ in flag_notes):  # the flags said controlled: the AI raised it
                flag_notes = [(code, note) for code, note in flag_notes if code != mild]
                flag_notes.append((strict, f"not under control is the AI's judgement: the clinic's {flag_kind} "
                                           "flags say controlled"))

    grouped: dict[str, dict] = {}
    for f in findings:
        g = grouped.setdefault(f.code, {"code": f.code, "name": ref.conditions[f.code]["name"],
                                        "bucket": ref.conditions[f.code]["bucket"], "found_by": set(),
                                        "complaint_only": True, "evidence": []})
        g["found_by"].add(f.found_by)
        g["complaint_only"] &= f.complaint_only
        line = f"{f.where}: \"{f.quote}\""
        if line not in g["evidence"]:
            g["evidence"].append(line)
    for code, note in flag_notes:
        if code in grouped:
            grouped[code]["evidence"].append(note)
    conditions = sorted(grouped.values(), key=lambda g: (g["bucket"] != "refer", g["code"]))
    for g in conditions:
        g["found_by"] = " + ".join(sorted(g["found_by"]))

    reasons = [f"{g['name']} ({g['code']}) needs a doctor" for g in conditions if g["bucket"] == "refer"]
    reasons += [f"Critical vital: {f['code']} = {f['value']} on {f['date']}"
                for f in context["vital_flags"] if f["severity"] == "CRITICAL"]
    reasons += [f"Recorded by a doctor as severe: {c['name']}" for c in context["conditions"]["doctor_recorded"]
                if str(c.get("severity") or "").upper() == "SEVERE"]
    reasons += [f"Emergency visit on {e['date']}" for e in context["alerts"]["emergencies"]]
    reasons += [f"{w['label']} in the complaint on {w['date']}: \"{w['complaint']}\"" for w in rules.warnings]
    if ai is None and not conditions:
        reasons.append("Assessment incomplete: the AI was unavailable and the rules found no condition")
    if ai is not None and ai["severity"] == "severe":
        reasons.append(f"AI rated it severe: {ai['problem']}")

    reasons = list(dict.fromkeys(reasons))  # the clinic can hold the same flag twice
    severity = "severe" if reasons else (ai["severity"] if ai is not None else "moderate")
    return {"codes": [g["code"] for g in conditions] or ["none"], "conditions": conditions,
            "severity": severity, "severe_reasons": reasons}
