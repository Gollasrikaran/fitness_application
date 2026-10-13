# Voice Activity Logging — Implementation Handoff Plan

**Audience:** an AI engineer (Gemini) implementing this blind, with no memory of how this
plan was derived. Every fact below was verified against the real code at the time this
was written — file:line references are exact, not approximate. If anything here
contradicts what you actually find in the repo, **trust the repo and flag the mismatch**
— do not silently guess past it.

**Status:** supersedes `docs/Voice_Activity_Logging_Implementation_Plan.md` (the earlier
"local-model-first, Gemini-cloud-fallback, Dexie/service-worker" design). That plan is
now obsolete for one concrete, tested reason: we benchmarked 4 local on-device models
(LaMini-Flan-T5-77M, SmolLM2-360M-Instruct, Qwen2.5-0.5B-Instruct, Qwen2.5-1.5B-Instruct
quantized) against this exact structured-extraction task and none were reliable —
failures ranged from producing no valid output at all, to hallucinating activities that
were never spoken, to multi-minute repetition-loop hangs. Full results live only in this
conversation's history, not a committed doc — **do not go looking for a benchmark
report file, there isn't one; this paragraph is the record of that decision.** The
product decision made from that result: **use the OpenRouter API as the only extraction
engine for v1.** No local model, no Dexie, no service worker, no offline queue, no
download-the-model popup. If a later iteration wants to revisit local models, that's
new work, not part of this plan.

---

## 1. The exact UX flow (do not deviate from this without asking)

1. User taps the mic button (already exists in the UI as a non-functional stub — see
   §3.1 for its exact current location).
2. Browser's Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`) captures
   microphone audio and converts it to a raw text transcript, client-side. No audio is
   ever uploaded or stored — only the resulting text leaves the browser.
3. The transcript is sent to a **new backend endpoint**, which calls the OpenRouter API
   to convert the free-form text into **structured JSON** (the exact schema is in §4.2).
4. A **plain code template — not another LLM call** — turns that structured JSON into a
   short human-readable summary sentence. This is a pure string-building function. Do
   not call any LLM for this step.
5. That summary sentence is spoken back to the user via the Web Speech API's
   `SpeechSynthesis` (`window.speechSynthesis.speak(...)`) — browser-native
   text-to-speech, no backend call needed for this step either.
6. A confirmation popup appears showing what was understood, visually styled to match
   the existing Workout Player's per-set tile pattern (§3.3 shows the exact pattern to
   reuse — e.g. "Walking — 2 km", "Glute Bridge — Set 1: 20, Set 2: 15, Set 3: 12").
7. From that popup, the user has exactly four actions:
   - **Confirm** — saves everything shown, exactly as currently displayed (including
     any manual edits made in step 8), via the **existing** logging endpoints (§5.4).
     Popup closes. No new backend "save" endpoint is created — see §5.4 for why.
   - **Edit** — discards the current result entirely and restarts voice capture from
     step 2 (the user speaks again from scratch).
   - **Cancel** — closes the popup immediately. Nothing is saved. No API calls happen
     at all (not even a partial save).
   - **Manual correction** (a distinct, finer-grained action from "Edit") — the user
     can tap directly on any displayed value (an activity name, a set's number, a unit)
     on the popup and change it by hand, without discarding the rest or restarting
     voice capture. This must work for every field shown, not just some of them.

---

## 2. Architecture decisions already made — do not re-litigate these

- **OpenRouter only, no local model.** See the status note above.
- **One new backend endpoint, not two.** The backend's only new job is turning a
  transcript into structured JSON. The actual *saving* of that data reuses the
  **existing, already-tested** `/v1/activities` and `/v1/custom-exercises` endpoints —
  orchestrated from the frontend, exactly the way `playerSubmitSets()` and
  `logCustomCard()` already do today. Do not build a second backend endpoint that
  duplicates `log_activity()`'s logic. Reuse it.
- **No new database tables, no new migration.** Nothing here needs to persist state of
  its own. The `voice_llm` quota bucket already exists at the database level — see
  §4.4, no migration needed for that either.
- **Source tagging.** Every entry logged through this feature must be logged with
  `source: "voice"` on its `/v1/activities` payload — this value is **already** an
  accepted value (`LOG_SOURCES = {"manual", "voice"}`,
  `app/profile/service.py:72`), so this is just passing the right string, not a schema
  change.

---

## 3. Exact current state of the code you're integrating with

### 3.1 The mic button (what you're wiring up)

`frontend/index.html:210-215`, inside `<section id="s-home">` (the Dashboard), right
after the "Your Own Exercises" section, immediately before that section's closing
`</section>`:

```html
<!-- voice FAB -->
<div class="fixed bottom-24 right-container-margin z-50">
  <button onclick="voiceStub()" class="w-16 h-16 rounded-full bg-primary-fixed shadow-lg flex items-center justify-center text-on-primary-fixed active:scale-95 transition-all assistant-pulse">
    <span class="material-symbols-outlined text-[32px]">mic</span>
  </button>
</div>
```

`frontend/src/main.js:664`:
```js
function voiceStub() { toast("🎤 Voice logging is coming soon!"); }
```

Also exported at `frontend/src/main.js:1667-1678` inside a big `Object.assign(window, {...})`
block — **every new function you reference from an inline `onclick="..."` in
index.html must be added into this same `Object.assign` call**, or it will be
`undefined` at click time (Vite modules are not global; this is the existing, deliberate
mechanism the whole app uses for this).

> **Ignore** `app/devconsole/templates/app.html:252` and `:1122` — there is a second,
> near-identical `voiceStub` in the admin devconsole template. That is a separate,
> internal API-testing tool, **not** the real frontend. Do not touch it.

### 3.2 The real activity-logging contract you will call from the frontend

`POST /v1/activities` (`app/profile/routes.py:229-274`) already accepts a **batch** of
entries in one call:
```json
{"entries": [ { ... }, { ... } ]}
```
Each entry accepts (parsed in `app/profile/routes.py`'s `log()`, validated in
`app/profile/service.py:log_activity()`, signature at `app/profile/service.py:830-835`):

| field | type | notes |
|---|---|---|
| `activity_type` | string or omitted | one of the 12 taxonomy codes (§3.4). Exactly one of `activity_type`/`custom_exercise_id` must be set — `app/profile/service.py:836-837` raises if both or neither are given. |
| `custom_exercise_id` | string or omitted | id of a user's own custom exercise (§3.5) |
| `amount` | float | required unless `set_amounts` is given |
| `sets` | int | required unless `set_amounts` is given |
| `unit` | string | e.g. `"km"`, `"count"`, `"sec"` |
| `source` | string | **must be `"voice"` for everything this feature logs** |
| `set_amounts` | list of numbers, or omitted | **only valid with `activity_type`, rejected outright if `custom_exercise_id` is set** (`app/profile/service.py:847-848`: `"set_amounts is only supported for taxonomy activities."`). When given, `sets` and `amount` are derived automatically (`sets = len(set_amounts)`, `amount = average`) — do not also pass `sets`/`amount` alongside `set_amounts`. |

**Consequence for this feature:** a taxonomy-matched activity (`is_custom: false` in our
extraction schema, §4.2) can carry a full per-set breakdown via `set_amounts`. A
custom-named activity (`is_custom: true`) **cannot** — the backend rejects
`set_amounts` for custom exercises. For a custom activity with multiple values spoken
(e.g. "20 pushups, then 15 more"), the frontend must itself collapse that into
`sets = len(values)`, `amount = average(values)` before calling `/v1/activities` for
that entry — this exactly mirrors what `log_activity()` already does internally for
taxonomy entries (`app/profile/service.py:866-871`), just done client-side for the one
case the backend won't do it for you.

Response shape: `{"logged": [...], "streak": <int>}`, HTTP 201. Each item in `logged` is
either `{"id", "duplicate": true, "implausible", "total_volume"}` or
`{"id", "duplicate": false, "implausible", "total_volume", "prescription"}`.

### 3.3 The custom exercise contract

`POST /v1/custom-exercises` (`app/profile/routes.py:305-315`,
`app/profile/service.py:create_custom_exercise()` at line 1143):
```json
{"name": "Pushups", "measurement_types": ["reps"]}
```
`measurement_types` is 1-3 values from `{"reps", "distance", "duration"}`
(`CUSTOM_MEASUREMENT_UNITS`, `app/profile/service.py:1085`), mapping to units
`{"reps": "count", "distance": "km", "duration": "min"}`. Response includes `"id"` —
this is the `custom_exercise_id` to use in the following `/v1/activities` call.

**Before creating a new custom exercise, check for an existing one with the same name**
(case-insensitive) by calling the already-existing `GET /v1/custom-exercises` and
matching client-side — do not create a duplicate custom exercise every time the user
says "pushups" again. (There is no dedicated "find by name" endpoint; listing + matching
client-side is the existing pattern this app already uses elsewhere for similar
lookups.)

### 3.4 The real taxonomy (12 activities, exact codes — never invent a 13th)

From `data/activity_taxonomy.csv` (read-only — this feature must never write to it):

| `activity_type` | `prescription_type` | `amount_unit` | synonyms (pipe-delimited, lowercase) |
|---|---|---|---|
| `walk` | distance | km | walk\|walking\|went for a walk\|walked\|stroll |
| `glute_bridge` | reps | count | glute bridge\|bridge\|bridges\|hip bridge\|butt lift |
| `dead_bug` | reps | count | dead bug\|dead bugs\|deadbug |
| `shoulder_circles` | reps | count | shoulder circles\|shoulder rolls\|rolled my shoulders\|shoulder roll |
| `running` | distance | km | run\|running\|jog\|jogging\|went for a run\|ran |
| `ankle_circles` | reps | count | ankle circles\|ankle rotations\|ankle circle\|rotated my ankle |
| `wrist_circles` | reps | count | wrist circles\|wrist rotations\|wrist circle\|wrists |
| `calf_stretch` | hold | sec | calf stretch\|calves\|wall stretch\|calf |
| `hamstring_stretch` | hold | sec | hamstring stretch\|hamstrings\|seated hamstring\|leg stretch |
| `quad_stretch` | hold | sec | quad stretch\|thigh stretch\|quads\|quadriceps stretch |
| `neck_isometric` | hold | sec | neck hold\|neck isometric\|neck exercise\|isometric neck |
| `lower_back_side_stretch` | hold | sec | side stretch\|chair stretch\|lower back stretch\|seated side bend |

**Build the prompt's activity list from this CSV at request time** (read it the same
way `app/catalog/loader.py` already does), not as a hardcoded string — if the taxonomy
ever grows, this feature must not silently fall out of sync.

### 3.5 The visual pattern to match for the confirmation popup

`frontend/src/main.js:805-829`, `renderSetsTable()` — this is the **exact** tile style
("Set 1" + its own target value, a toggle-style tile on the left) already used in the
real Workout Player. The confirmation popup's per-set display should look like this,
not invent a new visual language:
```js
function renderSetsTable(i) {
  const targets = i.set_targets || Array(i.sets).fill(i.amount);
  const unit = i.prescription_type === "hold" ? "s" : "";
  $("pl-sets-table").innerHTML = targets.map((target, idx) => {
    const done = playerSetDone[idx];
    return `
    <div class="flex items-center gap-1.5 cursor-pointer select-none" onclick="playerToggleSet(${idx})" title="Tap to mark Set ${idx + 1} done">
      <div class="w-14 h-11 rounded-xl flex items-center justify-center shrink-0 shadow-sm transition-all
                  ${done ? "bg-primary-fixed" : "bg-white/70 border border-black/10"}">
        <span class="material-symbols-outlined text-[20px] ${done ? "text-on-primary-fixed" : "text-secondary"}">${done ? "check" : "chevron_right"}</span>
      </div>
      <div class="flex-1 h-11 rounded-xl px-sm flex items-center justify-between shadow-sm border transition-all
                  ${done ? "bg-white/80 border-primary/50" : "bg-white/75 border-black/5"}">
        <span class="text-xs font-bold text-on-background">Set ${idx + 1}</span>
        <span class="text-xs font-bold ${done ? "text-primary" : "text-secondary"}">${target}${unit}</span>
      </div>
    </div>`;
  }).join("");
}
```
For the voice popup, replace the "done/not-done toggle" semantics with "tap to manually
edit this value" (§6.3) — same visual tile, different tap behavior.

### 3.6 How OpenRouter is called everywhere else in this app — reuse this, do not write a new HTTP call

`app/rag/vectorstore.py:133` — `chat_complete(messages, api_key, model=CHAT_MODEL, ...)`
is, per its module docstring, **"the single canonical place these OpenRouter calls are
made."** It already handles retries, timeouts, truncation detection, and malformed-JSON
responses correctly (this took several rounds of production bug fixes — do not
re-implement any of this). **Import and call this function directly from the new voice
service module.** Do not write a new `urllib`/`requests` call to OpenRouter anywhere.

Constant for reference: `CHAT_MODEL = "openai/gpt-oss-20b"` (`app/rag/vectorstore.py:23`)
— reuse this same model for consistency unless there's a specific reason to pick a
different one (there isn't, for this task).

### 3.7 How the API key reaches a service function — follow this exact pattern

Never read `OPENROUTER_API_KEY` from the environment anywhere except
`app/platform/config.py` (already done, once, at boot). Every route reads it via
`current_app.config["APP_CONFIG"].openrouter_api_key` and passes it as an explicit
`openrouter_api_key: str` keyword argument into its service function, which passes it
straight to `vectorstore.chat_complete`. Mirror `app/rag/routes.py:21-33`'s
`_rag_config()` helper pattern exactly:
```python
def _rag_config():
    cfg = current_app.config["APP_CONFIG"]
    if not cfg.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")
    return cfg
```

### 3.8 The quota bucket — already reserved, just unused

`app/rag/models.py:36-37`:
```python
CheckConstraint(
    "quota_type IN ('rehab_llm','voice_llm','escalation_confirm')", name="quota_type_known"),
```
`'voice_llm'` is **already a legal value at the database level — no migration needed.**
The atomic increment/refund machinery (`app/rag/service.py`'s `_consume_quota()` at
line 684 and `_refund_quota()` at line 716) is **already parameterized** by
`quota_type` and `limit` specifically so a second bucket like this one can reuse it
without duplicating the logic (this is stated directly in `_consume_quota`'s own
docstring). Import and call these two functions directly from the new voice service
module, passing `quota_type="voice_llm"` and a new limit constant (§4.4) — do not
reimplement the atomic UPDATE-with-WHERE-clause pattern. (Yes, their names start with
an underscore; that's an existing convention wrinkle, not a reason to copy the logic —
see §7 for the exact import line to use and why.)

### 3.9 Blueprint registration pattern

`app/factory.py` imports each feature's blueprint locally inside `create_app()` and
registers it, e.g.:
```python
from app.rag.routes import bp as rehab_bp
app.register_blueprint(rehab_bp)
```
and each `routes.py` defines its blueprint the same way, e.g.
`app/rag/routes.py:11`: `bp = Blueprint("rehab", __name__, url_prefix="/v1/rehab")`.
The new voice blueprint must follow this exact shape (§5.1).

---

## 4. Backend — new code

### 4.1 Files to CREATE

```
app/voice/__init__.py          (empty — just makes it a package)
app/voice/routes.py            (new blueprint, one route)
app/voice/service.py           (extraction logic, prompt building, quota)
tests/test_voice_extraction.py (new test file)
```

### 4.2 The extraction output schema — exact, do not deviate

```json
[
  {
    "activity_type": "walk",
    "activity_name": null,
    "is_custom": false,
    "set_amounts": [2],
    "unit": "km",
    "duration_minutes": 15
  },
  {
    "activity_type": null,
    "activity_name": "pushups",
    "is_custom": true,
    "set_amounts": [20],
    "unit": "count",
    "duration_minutes": null
  }
]
```

Rules (these were arrived at through real testing — follow them precisely):
- **`set_amounts` is always a list, even for a single value** — this is what lets one
  schema represent both "walked 2km" (`[2]`) and "glute bridge, 20 then 15 then 12"
  (`[20, 15, 12]`) uniformly.
- **`activity_type` must be an exact taxonomy code from §3.4, or `null` — never a
  synonym, never a raw spoken word.** (Testing showed small/weak models fail this rule
  constantly — e.g. returning `"jog"` instead of `"running"`. `gpt-oss-20b` should not
  have this problem, but validate the response against the real taxonomy list anyway
  before trusting it — see §4.3's validation step.)
- **If the spoken activity doesn't match any of the 12 taxonomy codes or their
  synonyms**, set `activity_type: null`, `is_custom: true`, and put the spoken word in
  `activity_name`.
- **Never invent a value that wasn't actually spoken.** If no duration was mentioned,
  `duration_minutes` must be `null`, not a guess.
- **One array item per activity actually mentioned in the sentence** — do not add
  activities that weren't said, and do not merge two different activities into one
  item.

### 4.3 `app/voice/service.py` — what it must do

```python
def extract_activities(session, user_id, transcript, *, openrouter_api_key) -> dict:
```

Exact verified exception classes (`app/platform/errors.py:54-60`):
```python
class RateLimited(ApiError):
    status, code = 429, "rate_limited"

class QuotaExhausted(ApiError):
    """A user-facing exhausted state — never a silent failure (5.5)."""
    status, code = 429, "quota_exhausted"
```
`QuotaExhausted` = the user hit their own daily cap. `RateLimited` = an infrastructure
hiccup on a call that already consumed (and then refunded) a quota slot. Follow this
**exact** sequence — the ordering and the explicit early `session.commit()` calls are
not optional, they fix a real, previously-shipped bug (see the comment quoted below):

1. **Consume quota first, unconditionally**, mirroring `app/rag/service.py:1429-1433`'s
   exact pattern (the escalation-confirmation quota, the closest existing analog):
   ```python
   if not _consume_quota(session, user_id, quota_type=VOICE_QUOTA_TYPE, limit=VOICE_DAILY_LIMIT):
       raise QuotaExhausted(
           "You've used your voice logging attempts for today — try again tomorrow, "
           "or log this one manually."
       )
   session.commit()  # durable immediately — see step 4, this must survive a later rollback
   ```
2. **Build the prompt** from the live taxonomy (§3.4, read fresh from the DB/CSV loader
   the same way the rest of `app/catalog` does it — do not hardcode the activity list
   as a Python string literal that can drift from the real data).
3. **Call `vectorstore.chat_complete(messages, openrouter_api_key, model=CHAT_MODEL)`**
   with the transcript embedded in the prompt.
4. **On any failure from `chat_complete`** (`UpstreamUnavailable` or
   `ResponseTruncated`, both defined in `app/rag/vectorstore.py:36-52`), mirror
   `app/rag/service.py:1358-1371` **exactly**, including the explicit commit **before**
   raising:
   ```python
   except (UpstreamUnavailable, ResponseTruncated):
       _refund_quota(session, user_id, quota_type=VOICE_QUOTA_TYPE)
       session.commit()  # critical — without this, the refund is rolled back by the
                          # same exception that triggers RateLimited's error response,
                          # silently re-inverting the bug this pattern already fixed once
       raise RateLimited(
           "Voice extraction is busy right now. Please try again in a moment — "
           "this attempt was not counted against your daily limit.",
           retry_after=30,
       )
   ```
5. **Parse and validate the response** — extract the JSON array (tolerate markdown code
   fences and surrounding prose, same defensive parsing approach used when building and
   testing the prompt for this exact task). For each returned item:
   - Verify `activity_type` is either `null` or one of the 12 real codes from §3.4 — if
     the model returns something else (a hallucinated or non-exact code), treat that
     item as `is_custom: true` with the returned string moved into `activity_name`
     instead of trusting it as a real taxonomy code. **Never let an invalid
     `activity_type` reach `/v1/activities` later** — that call would just 404/422 and
     strand the user.
   - Verify `set_amounts` is a non-empty list of positive numbers — drop/flag any item
     that isn't (do not silently invent a number).
   - If parsing fails entirely (not valid JSON, or not a list), return a result
     indicating total extraction failure so the frontend falls through to manual entry
     — do not raise an unhandled exception up through the route.
6. **Return** the validated structured array (service function returns a dict like
   `{"entries": [...], "transcript": transcript}` — route wraps it in `jsonify`).

Error classes to reuse (do not invent new ones) — check `app/platform/errors.py` for
the exact existing names before writing this; the rehab chat's quota-exhausted path
(`app/rag/routes.py`'s handling around `answer_query`) is the pattern to copy.

### 4.4 New config constant

`app/rag/service.py:49,55` — the exact existing constants to sit this next to:
```python
QUOTA_TYPE = "rehab_llm"
...
DAILY_LIMIT = 5
```
These are **plain hardcoded module constants** — not read from an environment variable
(verified: `app/platform/config.py` does have a generic `_int(name, default)` env-reader
helper at line 43, used elsewhere in that file, but `DAILY_LIMIT` itself does not use
it). **Match this exact convention, do not introduce a new one.** Add, in the same file:
```python
VOICE_QUOTA_TYPE = "voice_llm"
VOICE_DAILY_LIMIT = 60
```
right next to the existing pair, as a plain hardcoded constant — the same way its
sibling is defined, no env override.

**Why 60, not 5:** OpenRouter is now the *primary* path for every voice log, not a rare
fallback — the old spec's "5 fallbacks/day" number was sized for a rare-fallback role
and would block normal daily use if reused here unchanged.

### 4.5 `app/voice/routes.py`

```python
bp = Blueprint("voice", __name__, url_prefix="/v1/voice")


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Expected a JSON object body.")
    return data


def _str_field(d: dict, key: str, default: str = "") -> str:
    # Copy app/profile/routes.py:33's exact validation logic (type + strip + required
    # check) — do not import it from another blueprint, see §5.3's note on this
    # codebase's per-blueprint local-helper convention.
    ...


def _voice_config():
    cfg = current_app.config["APP_CONFIG"]
    if not cfg.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured; voice logging cannot run yet.")
    return cfg


@bp.post("/extract")
@require_auth
def extract():
    d = _body()
    transcript = _str_field(d, "transcript")
    cfg = _voice_config()
    with session_scope() as s:
        return jsonify(service.extract_activities(
            s, g.user_id, transcript, openrouter_api_key=cfg.openrouter_api_key,
        ))
```

**This codebase's convention is a small LOCAL copy of `_body()`/`_str_field()` per
blueprint file, not a shared import** — confirmed: `app/profile/routes.py:26`,
`app/rag/routes.py:14`, and `app/auth/routes.py:15` each define their own near-identical
`_body()`. `app/rag/routes.py:14-18`'s version is the simplest reference to copy:
```python
def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Expected a JSON object body.")
    return data
```
Add an equally small local `_body()` (and a `_str_field()` if needed — copy
`app/profile/routes.py:33`'s version) directly into `app/voice/routes.py`. Do not
import these from another blueprint's routes module, and do not create a new shared
platform helper module just for this — that would be inventing a new convention this
codebase doesn't use.

### 4.6 Register the blueprint

In `app/factory.py`, alongside the existing rehab blueprint registration:
```python
from app.voice.routes import bp as voice_bp
app.register_blueprint(voice_bp)
```
Gate it the same way `rehab_bp` is gated (`if cfg.service_role in ("all", "chat")`) —
this feature calls OpenRouter just like the rehab chat does, and should share the same
capacity-isolation reasoning (a slow voice-extraction call must never block login or
dashboard requests, same reason the chat service can be split onto its own instance).

---

## 5. Frontend — new code

### 5.1 State machine (add to `frontend/src/main.js`)

New module-level state (next to the existing `PLAYER_ITEMS`/`playerIndex`-style state
at the top of the player section):
```js
let voiceTranscript = "";
let voiceEntries = [];       // the structured array from the backend, editable in place
let voiceRecognition = null; // the SpeechRecognition instance
```

New functions to add (all must be added to the `Object.assign(window, {...})` block,
§3.1):

- **`startVoiceLogging()`** — replaces `voiceStub()`'s wiring on the mic button.
  - Feature-detect: `window.SpeechRecognition || window.webkitSpeechRecognition`. If
    absent, skip straight to the typing fallback (§6.4) — do not show a broken mic UI.
  - Request mic permission implicitly via starting recognition; handle the
    `onerror` event for `"not-allowed"` (permission denied) by falling through to the
    typing fallback with a clear message, not a silent failure.
  - On `onresult`, capture the transcript, call `voiceSubmitTranscript(transcript)`.
  - On `onerror` for `"no-speech"`, toast a friendly message and return to idle — do
    **not** open the confirmation popup with nothing in it.

- **`async function voiceSubmitTranscript(transcript)`** — POSTs `{transcript}` to
  `/v1/voice/extract` via the existing `api()` helper (`frontend/src/main.js:81`, the
  same one every other endpoint call in this file already uses — do not write a new
  fetch wrapper). On success, store the result in `voiceEntries`, call
  `renderVoiceConfirmation()`. On failure (quota exhausted, extraction failed,
  network error), fall through to the typing/manual fallback (§6.5) with a clear toast
  — never a dead end.

- **`buildHumanSummary(entries)`** — **pure string-building function, no API call.**
  Example:
  ```js
  function buildHumanSummary(entries) {
    return entries.map(e => {
      const name = e.activity_name || e.activity_type;
      const sets = e.set_amounts;
      const setsText = sets.length > 1
        ? `${sets.length} sets: ${sets.join(", ")}`
        : `${sets[0]}`;
      const unitText = e.unit && e.unit !== "count" ? ` ${e.unit}` : (sets.length === 1 ? " reps" : "");
      const durationText = e.duration_minutes ? ` in ${e.duration_minutes} minutes` : "";
      return `${name}: ${setsText}${unitText}${durationText}`;
    }).join(". ");
  }
  ```
  (Adjust phrasing to taste, but it must stay a template — no LLM call here, per the
  explicit product requirement.)

- **`speakSummary(text)`**:
  ```js
  function speakSummary(text) {
    if (!window.speechSynthesis) return; // feature-detect, never throw if unsupported
    window.speechSynthesis.cancel(); // stop any previous utterance first
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }
  ```

- **`renderVoiceConfirmation()`** — renders the popup (new markup, §5.2) using the
  tile pattern from §3.5, one tile per `set_amounts` value per entry. Each tile's
  `onclick` opens manual correction (§6.3) for that one value, not a toggle.

- **`confirmVoiceLog()`** — see §5.4, the save orchestration.

- **`editVoiceLog()`** — closes the popup, calls `startVoiceLogging()` again (restart
  capture from scratch, per §1 step 7's "Edit").

- **`cancelVoiceLog()`** — closes the popup, clears `voiceEntries`, makes no API calls.

### 5.2 New popup markup (add to `frontend/index.html`)

Follow the existing modal pattern already used for `catalogue-modal`/`cond-modal`
(same hidden/flex toggle convention, same backdrop style) — find one of those and copy
its outer structure, then fill it with:
- A title ("Here's what I heard")
- The per-entry tiles (§3.5's pattern, one row of tiles per entry, each tile tap-to-edit)
- Three buttons: Confirm, Edit, Cancel, wired to the three functions above.

### 5.3 Manual correction of a single value

When a tile is tapped, use the same lightweight pattern already used elsewhere in this
file for a single-value correction — `renameCustomPrompt()`
(`frontend/src/main.js`, search for it) uses `window.prompt(...)` for a simple one-value
edit. Reuse that same approach here: `window.prompt("Set 2:", currentValue)`, parse the
result as a number, update `voiceEntries[i].set_amounts[j]` in place, re-render the
popup. Do not build a more complex inline-input system than the rest of this codebase
already uses for equivalent single-value edits.

### 5.4 Confirm → save, via EXISTING endpoints only

```js
async function confirmVoiceLog() {
  const customLookup = await api("GET", "/v1/custom-exercises"); // existing endpoint
  const existingByName = new Map(
    customLookup.custom_exercises.map(c => [c.name.toLowerCase(), c.id])
  );
  const entries = [];
  for (const e of voiceEntries) {
    if (!e.is_custom) {
      entries.push({
        activity_type: e.activity_type,
        set_amounts: e.set_amounts,
        unit: e.unit,
        source: "voice",
      });
      continue;
    }
    // Custom path — find-or-create, then collapse set_amounts (backend rejects
    // set_amounts for custom exercises — see §3.2).
    let customId = existingByName.get(e.activity_name.toLowerCase());
    if (!customId) {
      const measurementType = e.unit === "km" ? "distance" : e.unit === "min" ? "duration" : "reps";
      const created = await api("POST", "/v1/custom-exercises", {
        name: e.activity_name, measurement_types: [measurementType],
      });
      customId = created.id;
    }
    const sets = e.set_amounts.length;
    const amount = e.set_amounts.reduce((a, b) => a + b, 0) / sets;
    entries.push({
      custom_exercise_id: customId, amount, sets, unit: e.unit, source: "voice",
    });
  }
  const result = await api("POST", "/v1/activities", { entries });
  // Same post-save pattern already used elsewhere (e.g. logCustomCard) — toast +
  // refresh whichever screen is currently showing logged data.
  toast(`Saved · ${result.streak.current} day streak`);
  cancelVoiceLog(); // close popup, clear state
  if (document.getElementById("s-home").classList.contains("on")) loadHome();
}
```

### 5.5 Typing fallback

If speech recognition is unsupported, permission is denied, or extraction fails: show a
plain text input feeding the exact same `voiceSubmitTranscript(text)` function — the
backend doesn't know or care whether the text came from speech or typing. Do not build
a second extraction path for typed input.

---

## 6. Testing

Create `tests/test_voice_extraction.py` following the **exact** pattern already used in
`tests/test_rag_quota_refund.py` — real-Postgres integration tests, not mocked-HTTP
unit tests:
- Use the `make_user` fixture (`tests/conftest.py`) for test accounts.
- `monkeypatch.setattr(vectorstore, "chat_complete", fake_fn)` to control what the
  "model" returns, rather than mocking HTTP.
- Test at minimum: (1) a clean single-activity extraction round-trip, (2) a
  multi-activity sentence producing multiple array items, (3) quota exhaustion after
  `VOICE_DAILY_LIMIT` calls, (4) quota refund on a simulated `UpstreamUnavailable`
  (mirror `test_response_truncated_refund_is_durable` almost exactly), (5) an
  unparseable/garbage model response falling through cleanly instead of crashing, (6)
  a hallucinated non-taxonomy `activity_type` getting correctly demoted to
  `is_custom: true` rather than reaching the client as an invalid code.

---

## 7. Files you MUST NOT modify (beyond their one listed exception), and why

| Path | Why it's off-limits |
|---|---|
| `app/progression/*` | Unrelated system (per-set progression engine). No voice-logging change should ever touch this. |
| `app/catalog/*`, `data/*.csv` | The taxonomy/safety-grid data and its loader. This feature only **reads** taxonomy data at request time — never writes to it, never modifies the loader. |
| `app/rag/vectorstore.py` | Import `chat_complete`, `CHAT_MODEL`, `UpstreamUnavailable`, `ResponseTruncated` from it. Do not edit it — zero changes, not even the narrow exception the next row gets. |
| `app/rag/models.py` | `voice_llm` is already a legal `quota_type` value — no migration, no model change needed here. Zero changes. |
| `app/rag/service.py` | **The one file with a narrow, bounded exception — see §4.4/§8, not a blanket "don't touch."** The ONLY change allowed is adding the two new constants (`VOICE_QUOTA_TYPE`, `VOICE_DAILY_LIMIT`) next to their existing siblings. Beyond that: import `_consume_quota`/`_refund_quota` directly by their existing (underscore-prefixed) names from elsewhere — e.g. `from app.rag.service import _consume_quota, _refund_quota` — do not rename them, do not refactor this file otherwise, do not duplicate their atomic-UPDATE logic inline instead. |
| Any `migrations/versions/*` file (existing ones) | Nothing in this plan needs a new migration at all — don't create one, and definitely don't edit an existing one. |
| `frontend/index.html` / `frontend/src/main.js` — everything NOT related to the mic button and the new popup | Dashboard layout, Workout Player exercise-logging logic, onboarding, chat, settings, profile — none of this should change. Add new code; do not refactor adjacent existing code "while you're in there." |
| `app/devconsole/*` | Internal admin tool, not the real frontend — ignore its parallel `voiceStub`. |

## 8. Files you WILL create or modify — final checklist

**Create:**
- `app/voice/__init__.py`
- `app/voice/routes.py`
- `app/voice/service.py`
- `tests/test_voice_extraction.py`

**Modify:**
- `app/factory.py` — register the new blueprint (§4.6)
- `app/rag/service.py` — add the `VOICE_DAILY_LIMIT` constant only (§4.4); no other
  change to this file
- `frontend/index.html` — change the mic button's `onclick`, add the new popup markup
- `frontend/src/main.js` — add the new functions listed in §5.1, add them to the
  existing `Object.assign(window, {...})` export block, remove the old `voiceStub()`

**Do not touch anything else.** If you find yourself wanting to edit a file not listed
in either list above, stop and treat that as a signal this plan is missing something —
do not improvise past it silently.
