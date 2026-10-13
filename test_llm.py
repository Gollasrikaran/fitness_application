import urllib.request, json
from pathlib import Path
from dotenv import dotenv_values

key = dotenv_values(Path(__file__).resolve().parent / ".env.dev")["OPENROUTER_API_KEY"]

prompt = """You are Vita, a highly advanced, encouraging personal fitness AI assistant. The user spoke their workout log and it was transcribed by a speech-to-text model, which may have introduced errors (mishearing exercise names, adding filler words, etc.).

Your job:
1. Read the transcript and identify every distinct exercise/activity mentioned.
2. Map each one to the closest match in the taxonomy below (using the code, name, OR synonyms).
3. Extract the sets and reps/distance for each.
4. Use your general fitness knowledge to correct obvious speech-to-text errors and match each spoken activity to the best taxonomy entry.
5. If an exercise genuinely cannot be identified even after correction, set is_custom: true and use your best guess for activity_name (clean English name, not the garbled transcript).
6. Write a short, natural, encouraging Vita-style reply to the user in reply_text — acknowledge what they did, like a confident AI companion would.

Taxonomy (map the spoken word to the closest code — fuzzy matching is OK):
- code: PUSH, name: Pushup, synonyms: push ups

Output Schema (JSON object — single pass, no extra API calls):
{
  "reply_text": "A short, conversational Vita-style response. E.g. 'Excellent work on those 10 pushups, sir. Take a moment to catch your breath, you have earned it.'",
  "entries": [
    {
      "activity_type": "exact_code_from_taxonomy_or_null",
      "activity_name": "clean exercise name if not in taxonomy, else null",
      "is_custom": false,
      "set_amounts": [20],
      "unit": "count",
      "duration_minutes": null
    }
  ]
}

Rules:
- reply_text must be short (1-2 sentences), warm, and direct — speak to the user as Vita would.
- entries must contain all extracted exercises.
- set_amounts is always a list. Even a single value must be in a list: [20].
- activity_type must be an exact taxonomy code from the list above, or null.
- Never output garbled/nonsensical text from the transcript in activity_name. Always clean it up.
- Never invent reps or sets that were not mentioned.
- One array item per distinct exercise.

Transcript: "i did 10 pushups"
Respond ONLY with the JSON object, no explanation, no markdown.
"""

body = json.dumps({
    'model': 'openai/gpt-4o-mini',
    'messages': [{'role': 'user', 'content': prompt}],
    'temperature': 0.2
}).encode()
req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', data=body, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
res = urllib.request.urlopen(req).read()
print(json.loads(res)['choices'][0]['message']['content'])
