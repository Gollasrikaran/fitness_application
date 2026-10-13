import json
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.catalog.models import ActivityTaxonomy
from app.platform.errors import QuotaExhausted, RateLimited
from app.rag.service import _consume_quota, _refund_quota, VOICE_QUOTA_TYPE, VOICE_DAILY_LIMIT
from app.rag.vectorstore import chat_complete, VOICE_CHAT_MODEL, UpstreamUnavailable, ResponseTruncated

def extract_activities(session: Session, user_id: str, transcript: str, *, openrouter_api_key: str) -> dict:
    if not _consume_quota(session, user_id, quota_type=VOICE_QUOTA_TYPE, limit=VOICE_DAILY_LIMIT):
        raise QuotaExhausted(
            "You've used your voice logging attempts for today — try again tomorrow, "
            "or log this one manually."
        )
    session.commit()

    rows = session.execute(
        select(ActivityTaxonomy.activity_type, ActivityTaxonomy.display_name, ActivityTaxonomy.synonyms)
    ).all()
    
    valid_codes = set()
    taxonomy_list = []
    for code, name, synonyms in rows:
        valid_codes.add(code)
        syn_str = " | ".join(synonyms) if synonyms else "none"
        taxonomy_list.append(f"- code: {code}, name: {name}, synonyms: {syn_str}")
    
    taxonomy_str = "\n".join(taxonomy_list)

    prompt = f"""You are Vita, a highly advanced, encouraging personal fitness AI assistant. The user spoke their workout log and it was transcribed by a speech-to-text model, which may have introduced errors (mishearing exercise names, adding filler words, etc.).

Your job:
1. Read the transcript and identify every distinct exercise/activity mentioned.
2. Map each one to the closest match in the taxonomy below (using the code, name, OR synonyms).
3. Extract the sets and reps/distance for each.
4. Use your general fitness knowledge to correct obvious speech-to-text errors and match each spoken activity to the best taxonomy entry.
5. If an exercise genuinely cannot be identified even after correction, set is_custom: true and use your best guess for activity_name (clean English name, not the garbled transcript).
6. Write a short, natural, encouraging Vita-style reply to the user in reply_text — acknowledge what they did, like a confident AI companion would.

Taxonomy (map the spoken word to the closest code — fuzzy matching is OK):
{taxonomy_str}

Output Schema (JSON object — single pass, no extra API calls):
{{
  "reply_text": "A short, conversational Vita-style response. E.g. 'Excellent work on those 10 pushups, sir. Take a moment to catch your breath, you have earned it.'",
  "entries": [
    {{
      "activity_type": "exact_code_from_taxonomy_or_null",
      "activity_name": "clean exercise name if not in taxonomy, else null",
      "is_custom": false,
      "set_amounts": [number, number, ...],
      "unit": "km or count or sec or min",
      "duration_minutes": null
    }}
  ]
}}

Rules:
- reply_text must be short (1-2 sentences), warm, and direct — speak to the user as Vita would.
- entries must contain all extracted exercises.
- set_amounts is an array where EACH item represents ONE set's reps or distance. 
- CRITICAL: If the transcript specifies multiple sets, you MUST output an array containing the reps repeated for each set (e.g., "X sets of Y reps" becomes [Y, Y, ... repeated X times]). Do NOT just extract the set count.
- Even a single set must be in a list.
- activity_type must be an exact taxonomy code from the list above, or null.
- Never output garbled/nonsensical text from the transcript in activity_name. Always clean it up.
- Never invent reps or sets that were not mentioned.
- One array item per distinct exercise.

Transcript: "{transcript}"
Respond ONLY with the JSON object, no explanation, no markdown.
"""

    messages = [{"role": "user", "content": prompt}]

    try:
        raw_response = chat_complete(messages, openrouter_api_key, model=VOICE_CHAT_MODEL)
    except (UpstreamUnavailable, ResponseTruncated):
        _refund_quota(session, user_id, quota_type=VOICE_QUOTA_TYPE)
        session.commit()
        raise RateLimited(
            "Voice extraction is busy right now. Please try again in a moment — "
            "this attempt was not counted against your daily limit.",
            retry_after=30,
        )

    try:
        raw_response = raw_response.strip()
        if raw_response.startswith("```"):
            raw_response = raw_response.strip("`")
            if raw_response[:4].lower() == "json":
                raw_response = raw_response[4:]
        print(f"RAW LLM RESPONSE: {raw_response}", flush=True)
        data = json.loads(raw_response)

        # Fallback: LLM returned the old array format instead of the new object format
        if isinstance(data, list):
            data = {"entries": data, "reply_text": "Got it!"}
        
        if not isinstance(data, dict):
            return {"entries": [], "transcript": transcript, "reply_text": "Got it!"}

        entries_raw = data.get("entries", [])
        if not isinstance(entries_raw, list):
            entries_raw = []
        reply_text = data.get("reply_text", "Got it!")

        entries = []
        for item in entries_raw:
            if not isinstance(item, dict):
                continue
                
            code = item.get("activity_type")
            if code is not None and code not in valid_codes:
                item["activity_type"] = None
                item["is_custom"] = True
                item["activity_name"] = code
                
            sets = item.get("set_amounts")
            if not isinstance(sets, list) or len(sets) == 0:
                continue
            
            valid_sets = []
            for s in sets:
                if isinstance(s, (int, float)) and not isinstance(s, bool) and s > 0:
                    valid_sets.append(s)
            
            if not valid_sets:
                continue
            item["set_amounts"] = valid_sets
            entries.append(item)
            
        return {"entries": entries, "transcript": transcript, "reply_text": reply_text}

    except json.JSONDecodeError:
        return {"entries": [], "transcript": transcript, "reply_text": "Got it!"}
