"""Module 5 — Rehab & Pain Guidance.

The safety boundary that shapes everything here: the model explains using only the
retrieved text handed to it. It may name a specific exercise ONLY if the reviewed
safety grid (13.3) has verdicted it "safe" for the user's condition — that closed,
human-reviewed list is fed into every prompt; the model never invents or picks one
outside it. If nothing approved fits the question, it falls back to general
self-care basics (gentle stretching, ice/heat, gentle movement, rest, sleep,
nutrition) rather than declining outright. It never names a medication, dose,
brand, or surgical procedure — those always go back to a doctor or pharmacist, and
that rule is enforced twice: once in the prompt, and again by a runtime keyword
check afterward (`_enforce_no_medication_or_surgery`), since a free-tier model
doesn't always obey a prompt instruction 100% of the time. Referred-bucket users
get the referral message and nothing else (13.3b), and never consume quota
getting it.

5.6 — a symptom description ("my lower back hurts") is not a condition. The model may
suggest a match from the closed list, but recording it always requires a separate,
explicit confirmation from the client (a tap), never the suggestion step itself.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.catalog.models import ActivityTaxonomy, Condition, SafetyGridCell
from app.platform.errors import QuotaExhausted, RateLimited, ValidationError
from app.profile.models import UserCondition, UserProfile
from app.profile.service import (
    IST, REFERRAL_MESSAGE, complete_onboarding, is_referred, today_ist,
)
from app.rag import vectorstore
from app.rag.models import RehabQuota
from app.rag.vectorstore import UpstreamUnavailable

QUOTA_TYPE = "rehab_llm"
DAILY_LIMIT = 5
MAX_QUESTION_LENGTH = 500
MIN_LENGTH_WORTH_CLASSIFYING = 15  # skip the extra LLM call for "hi"-length messages

SYSTEM_PROMPT = """You are a rehab and pain guidance assistant inside a beginner-level \
fitness app for adults in India. You answer questions about a user's selected health \
condition using ONLY the "Retrieved information" provided in each message — never add \
outside medical knowledge, and never guess if the retrieved information doesn't cover \
the question.

Strict rules, no exceptions:
1. You may name a specific exercise ONLY if it appears in the "Approved exercises for \
this condition" list given to you in the message. That list comes from a separate, \
reviewed safety system — never invent, pick, or suggest an exercise outside it, even \
if the retrieved text names one. If none of the approved exercises fit the question, \
or the list says none are listed, do not just decline — instead offer general \
self-care basics (e.g. gentle stretching, applying ice or heat, gentle movement, \
rest, adequate sleep, balanced nutrition) without naming any specific unlisted \
exercise.
2. Never name a specific medication, drug class, dose, or brand, even if one appears in \
the retrieved text. If the question is about medication, say this is something to \
discuss with a doctor or pharmacist, and stop there.
3. Never name a specific surgical procedure or intervention (e.g. laminectomy, spinal \
fusion, discectomy, carpal tunnel release), even if one appears in the retrieved \
text. If the question is about surgery, say this is something to discuss with a \
doctor, and stop there.
4. If the retrieved information doesn't answer the question, say so plainly and suggest \
seeing a doctor — do not fill the gap with general knowledge.
5. Keep answers short, plain-language, and calm. This is a general-audience app, not a \
clinical tool.
6. Do not add any "this is general information, not medical advice"-style disclaimer. \
Just answer directly.
"""

CONDITION_MATCH_PROMPT = """A user of a fitness/rehab app wrote a message describing pain \
or discomfort. They have ALREADY told the app about: {existing}.

Decide: does the message describe a DIFFERENT problem than what's already known, that \
clearly matches one of these NOT-yet-selected conditions?

{options}

Message: "{question}"

Reply with exactly NONE if the message is a general or follow-up question that could \
reasonably relate to a condition they've already told the app about — most back/spine \
questions from a user who already reported a back/spine condition fall here, even if \
worded generally. Only reply with one of the codes above if the message clearly points \
to a genuinely different, not-yet-reported problem. This is only a suggestion the user \
confirms or declines afterward, so when it's a close call between "already covered" and \
"new," prefer NONE — the point is to catch clearly new complaints, not to relabel a \
question about something already known.

Reply with ONLY the exact code or exactly NONE, nothing else.
"""

NO_CONTENT_ANSWER = (
    "I don't have verified information for this yet. Please speak to a doctor about "
    "this question."
)

SAFETY_FALLBACK_ANSWER = (
    "I'm not able to provide a specific medication or surgery name — that's something "
    "to discuss directly with a doctor or pharmacist."
)

# Canonical lists for the runtime backstop below AND for tests/test_rag_safety.py
# (imported from there, not duplicated) — the prompt rules above ask the model not
# to say these, but a free-tier model doesn't always obey a prompt instruction, so
# this is checked again in code after the model answers.
MEDICATION_KEYWORDS = [
    "allopurinol", "febuxostat", "probenecid", "colchicine", "pegloticase",
    "nsaid", "ibuprofen", "naproxen", "acetaminophen", "aspirin", "paracetamol",
    "corticosteroid", "codeine", "tramadol", "gabapentin", "opioid", "diuretic",
]
SURGERY_KEYWORDS = [
    "laminectomy", "discectomy", "spinal fusion", "microdiscectomy",
    "arthroscopy", "arthroplasty", "carpal tunnel release", "fasciotomy",
]


def _enforce_no_medication_or_surgery(answer: str) -> str:
    """Runtime backstop for prompt rules 2-3: a free-tier model occasionally names a
    medication or surgical procedure despite being told not to (verified directly —
    the same question phrased two ways produced one compliant and one non-compliant
    answer). Rather than try to redact just the offending phrase from an otherwise
    coherent answer, replace the whole thing — a partially-redacted medical answer
    is worse than a clean decline."""
    lowered = answer.lower()
    if any(kw in lowered for kw in MEDICATION_KEYWORDS) or any(kw in lowered for kw in SURGERY_KEYWORDS):
        return SAFETY_FALLBACK_ANSWER
    return answer


def _approved_activities(session: Session, condition_codes: list[str]) -> list[str]:
    """Exercise display names the reviewed safety grid (13.3) has verdicted "safe"
    for any of this user's conditions — the ONLY exercises the prompt is allowed to
    let the model name. Everything else (verdict "modify"/"avoid", or simply not in
    the grid for this condition) is deliberately excluded; the model falls back to
    generic self-care guidance for those instead."""
    if not condition_codes:
        return []
    rows = session.execute(
        select(ActivityTaxonomy.display_name)
        .join(SafetyGridCell, SafetyGridCell.activity_type == ActivityTaxonomy.activity_type)
        .where(SafetyGridCell.condition_code.in_(condition_codes), SafetyGridCell.verdict == "safe")
        .distinct()
    ).all()
    return sorted({r[0] for r in rows})


def _reset_at_iso() -> str:
    """Midnight IST — the start of the next quota window (5.4, single-market IST per 3.3)."""
    tomorrow = (datetime.now(IST) + timedelta(days=1)).date()
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=IST).isoformat()


def remaining_quota(session: Session, user_id: str) -> dict:
    row = session.get(RehabQuota, (user_id, QUOTA_TYPE, today_ist()))
    used = row.count if row else 0
    return {
        "limit": DAILY_LIMIT,
        "used": used,
        "remaining": max(0, DAILY_LIMIT - used),
        "resets_at": _reset_at_iso(),
        # So the chat UI can show the referral message up front instead of
        # inviting a referred user to type into a box that will just reject them
        # (13.3b) — this is a courtesy for that screen, not itself the safety gate;
        # answer_query() below enforces the real block server-side regardless.
        "referred": is_referred(session, user_id),
        "referral_message": REFERRAL_MESSAGE if is_referred(session, user_id) else None,
    }


def _consume_quota(session: Session, user_id: str) -> bool:
    """5.4 — atomic increment-if-under-limit.

    A plain read-then-write would let two concurrent requests both read count=4 and
    both proceed. The UPDATE's WHERE clause makes the check and the increment one
    atomic operation: only a request that actually flips the row through 4->5 gets
    to say it was allowed. Row updated -> allow. No row updated -> block.
    """
    today = today_ist()
    session.execute(
        pg_insert(RehabQuota)
        .values(user_id=user_id, quota_type=QUOTA_TYPE, local_date=today, count=0)
        .on_conflict_do_nothing(index_elements=["user_id", "quota_type", "local_date"])
    )
    result = session.execute(
        update(RehabQuota)
        .where(
            RehabQuota.user_id == user_id,
            RehabQuota.quota_type == QUOTA_TYPE,
            RehabQuota.local_date == today,
            RehabQuota.count < DAILY_LIMIT,
        )
        .values(count=RehabQuota.count + 1)
    )
    return result.rowcount > 0


def _refund_quota(session: Session, user_id: str) -> None:
    """Undoes _consume_quota's increment when the reserved slot went to waste on
    an infrastructure failure (the LLM provider being rate-limited), not on the
    user asking something we couldn't answer. A user should not lose one of
    their 5 daily questions because OpenRouter's free tier was briefly overloaded
    — a real, recurring situation, not a rare edge case (see PART2 chat log)."""
    today = today_ist()
    session.execute(
        update(RehabQuota)
        .where(
            RehabQuota.user_id == user_id,
            RehabQuota.quota_type == QUOTA_TYPE,
            RehabQuota.local_date == today,
            RehabQuota.count > 0,
        )
        .values(count=RehabQuota.count - 1)
    )


def _condition_options(session: Session, user_id: str) -> list[dict]:
    """Supported conditions the user hasn't already selected — the only things
    it's meaningful to suggest (3.2's closed list, never anything else)."""
    existing = set(session.scalars(
        select(UserCondition.condition_code).where(UserCondition.user_id == user_id)
    ).all())
    rows = session.execute(
        select(Condition.condition_code, Condition.display_name)
        .where(Condition.bucket == "supported", Condition.condition_code != "none")
        .order_by(Condition.display_order)
    ).all()
    return [{"code": c, "label": n} for c, n in rows if c not in existing]


def _existing_condition_labels(session: Session, user_id: str) -> list[str]:
    rows = session.execute(
        select(Condition.display_name)
        .join(UserCondition, UserCondition.condition_code == Condition.condition_code)
        .where(UserCondition.user_id == user_id, Condition.condition_code != "none")
    ).all()
    return [r[0] for r in rows]


def _classify_condition(question: str, options: list[dict], existing_labels: list[str],
                         api_key: str) -> str | None:
    """Best-effort match of a symptom description to the closed condition list.

    Never trusted directly: the caller only uses this to SUGGEST, and the return
    value is validated against `options` before use either way. If the LLM is
    rate-limited, this just returns None (skip the suggestion, fall through to a
    normal answer attempt) rather than blocking the whole request on it.
    """
    if not options or len(question) < MIN_LENGTH_WORTH_CLASSIFYING:
        return None
    listing = "\n".join(f"{o['code']}: {o['label']}" for o in options)
    existing = ", ".join(existing_labels) if existing_labels else "nothing yet"
    prompt = CONDITION_MATCH_PROMPT.format(existing=existing, options=listing, question=question)
    try:
        reply = vectorstore.chat_complete(
            [{"role": "user", "content": prompt}], api_key, temperature=0,
        )
    except UpstreamUnavailable:
        return None
    reply = reply.strip().strip('"').strip("'")
    valid_codes = {o["code"] for o in options}
    if reply in valid_codes:
        return reply
    # The model doesn't always follow "reply with ONLY the code" to the letter —
    # tolerate a code appearing inside extra text/punctuation. None of our codes
    # are substrings of each other, so this can't cross-match the wrong one.
    lowered = reply.lower()
    for code in valid_codes:
        if code in lowered:
            return code
    return None


def _add_condition(session: Session, user_id: str, condition_code: str) -> dict:
    """Adds one condition to the user's existing profile without discarding the
    others — reuses the exact mechanism the app's own condition-editor screen
    already calls (profile.service.complete_onboarding with the merged list), so
    this isn't a second, divergent way to change conditions and doesn't risk
    the safety-grid rebuild behaving differently than it does elsewhere."""
    profile = session.get(UserProfile, user_id)
    existing_codes = list(session.scalars(
        select(UserCondition.condition_code).where(UserCondition.user_id == user_id)
    ).all())
    merged = [c for c in existing_codes if c != "none"]
    if condition_code not in merged:
        merged.append(condition_code)

    return complete_onboarding(
        session, user_id,
        age=profile.age, goal=profile.goal, experience_band=profile.experience_band,
        condition_codes=merged, unit_preference=profile.unit_preference,
    )


def _retrieve_and_answer(session: Session, user_id: str, question: str, *, rag_db_url: str,
                          openrouter_api_key: str) -> dict:
    if not _consume_quota(session, user_id):
        raise QuotaExhausted(
            "You've used all 5 questions for today. Come back tomorrow, or speak to a "
            "doctor if this feels urgent."
        )

    condition_codes = list(session.scalars(
        select(UserCondition.condition_code).where(UserCondition.user_id == user_id)
    ).all())

    try:
        chunks = vectorstore.retrieve_chunks(
            question, condition_codes, rag_db_url=rag_db_url, api_key=openrouter_api_key,
        )
        if not chunks:
            answer = NO_CONTENT_ANSWER
        else:
            context_block = "\n\n".join(f"[{i + 1}] {c['text']}" for i, c in enumerate(chunks))
            approved = _approved_activities(session, condition_codes)
            approved_block = (
                "Approved exercises for this condition: " + ", ".join(approved)
                if approved else
                "Approved exercises for this condition: none listed."
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",
                 "content": f"Retrieved information:\n{context_block}\n\n{approved_block}\n\n"
                            f"Question: {question}"},
            ]
            answer = _enforce_no_medication_or_surgery(
                vectorstore.chat_complete(messages, openrouter_api_key)
            )
    except UpstreamUnavailable:
        _refund_quota(session, user_id)
        raise RateLimited(
            "The guidance service is busy right now. Please try again in a moment — "
            "this attempt was not counted against your daily questions.",
            retry_after=30,
        )

    return {
        "referred": False, "message": None, "answer": answer,
        "needs_condition_selection": False, "condition_options": None,
        "quota": remaining_quota(session, user_id),
    }


def answer_query(session: Session, user_id: str, question: str, *, rag_db_url: str,
                  openrouter_api_key: str, condition_confirmation: dict | None = None) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValidationError("Ask a question first.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise ValidationError(f"Keep questions under {MAX_QUESTION_LENGTH} characters.")

    if is_referred(session, user_id):
        # No guidance at all (13.3b) — and no quota spent getting told that.
        return {
            "referred": True, "message": REFERRAL_MESSAGE, "answer": None,
            "needs_condition_selection": False, "condition_options": None,
            "quota": remaining_quota(session, user_id),
        }

    # A tap confirming (or declining) a condition suggested for THIS question.
    # 5.6: the model only ever suggests — recording a condition always requires
    # this separate, explicit step, never the classification below on its own.
    if condition_confirmation is not None:
        code = condition_confirmation.get("code")
        if code:
            valid_codes = {o["code"] for o in _condition_options(session, user_id)}
            if code not in valid_codes:
                raise ValidationError("Unknown or already-selected condition.")
            result = _add_condition(session, user_id, code)
            if result.get("referred"):
                return {
                    "referred": True, "message": result["message"], "answer": None,
                    "needs_condition_selection": False, "condition_options": None,
                    "quota": remaining_quota(session, user_id),
                }
        return _retrieve_and_answer(
            session, user_id, question, rag_db_url=rag_db_url,
            openrouter_api_key=openrouter_api_key,
        )

    # Fresh message: check whether it looks like an undiagnosed symptom
    # description before spending a quota slot on it (5.6). No quota is consumed
    # by this check either way — only a real answer (below, or after
    # confirmation) does that.
    options = _condition_options(session, user_id)
    existing_labels = _existing_condition_labels(session, user_id)
    matched_code = _classify_condition(question, options, existing_labels, openrouter_api_key)
    if matched_code:
        matched_label = next(o["label"] for o in options if o["code"] == matched_code)
        return {
            "referred": False, "message": None, "answer": None,
            "needs_condition_selection": True,
            "condition_options": {
                "prompt_text": "That sounds like it could be one of these — which fits?",
                "matched_code": matched_code,
                "matched_label": matched_label,
                "original_question": question,
            },
            "quota": remaining_quota(session, user_id),
        }

    return _retrieve_and_answer(
        session, user_id, question, rag_db_url=rag_db_url,
        openrouter_api_key=openrouter_api_key,
    )
