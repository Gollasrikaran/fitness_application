# Voice Activity Logging – Implementation Plan (Website)

**Status:** DRAFT for review. **Audience:** all users (not only older adults). **Platform:** website (responsive, installable optional), not a native app.

## 1. Goal

Let any user log a workout by speaking one sentence (e.g. "I walked 2 km in 15 minutes"). The site turns it into a structured record with no typing and no technical steps. Processing happens on the user's device by default; the cloud is used only if the user declines the on-device helper.

## 2. Design Principles (all ages)

- **Simple for everyone:** one big mic button, plain words, no settings to configure.
- **Accessibility:** WCAG 2.2 AA minimum (AAA contrast where feasible), body text 16–18px+, touch targets 48px+, full keyboard and screen-reader support, respects reduced-motion and OS dark mode.
- **No jargon in the UI:** never say AI, LLM, cache, model, quantized. Use "Private Offline Helper".
- **Always confirm:** every log shows a summary card ("We recorded: 2 km Walk (15 mins). Is this right?") with large "Looks Good" and "Try Again" buttons.
- **Always give feedback:** pulsing mic while listening, friendly progress text while setting up ("Setting up your private helper… 45%"), clear error messages with a typed-entry alternative.
- **Typing fallback:** if speech is unsupported or denied, show a text box that feeds the same pipeline.

## 3. Tech Stack

| Layer | Choice |
|---|---|
| Frontend | Vite web app, responsive. Reuse the existing frontend (currently vanilla JS + Tailwind) unless a React migration is approved – see Open Decisions. |
| Styling | Tailwind CSS with accessibility tokens (sizes, contrast, focus rings). |
| Speech-to-text | Browser Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`). |
| Local database | Dexie.js (IndexedDB). |
| Local extraction | Transformers.js in a Web Worker, model `Xenova/LaMini-Flan-T5-77M` (~80MB), plus a rule-based parser as validator/fallback. |
| Cloud extraction | Gemini API with structured (JSON-schema) output, called only from our backend. |
| Cloud database | Supabase Postgres with Row Level Security (or the existing backend DB – see Open Decisions). |
| Offline / caching | Service Worker (Workbox) for app shell and sync trigger; optional install prompt. |

## 4. Core Flow (on mic tap)

1. **Capture:** Web Speech API converts voice to a raw text string. Show live transcript.
2. Check Dexie `user_settings.model_downloaded`.
3. **If true:** send text to the Web Worker, get JSON, save to Dexie as status `parsed_local`, show confirmation card instantly.
4. **If false and no prior choice:** pause and show the Helper Download popup.
5. **Popup text:** "To make your voice logging private and instant (even without Wi-Fi), we need to download a secure, one-time helper file to your device." Buttons: Accept / No thanks.
6. **Accept:** download ~80MB with progress %, then immediately call `navigator.storage.persist()` so the browser does not evict it; save `model_downloaded` and `storage_persisted`; process the pending log locally.
7. **Reject:** save `cloud_fallback_accepted = true` so we never ask again; continue to cloud path.
8. **Cloud path (online):** POST raw text to backend, Gemini returns JSON, save as `parsed_cloud`, show confirmation card.
9. **Cloud path (offline):** save raw text as `pending_cloud_parse` and show "Recorded. Totals will update when Wi-Fi returns."
10. **Confirmation card:** Looks Good keeps the record; Try Again discards it and restarts capture.
11. **Background sync:** on the `online` event (and app start), push `parsed_local` / `parsed_cloud` records to the cloud DB; for `pending_cloud_parse` send text to backend, update Dexie, then push; mark all pushed records `synced`.

## 5. Data Schemas

### Dexie: `activities`

| Field | Type |
|---|---|
| id | auto-increment int |
| raw_text | string |
| structured_data | `{ activity: string, distance: number\|null, unit: string\|null, duration_minutes: number\|null }` |
| status | `parsed_local` \| `parsed_cloud` \| `pending_cloud_parse` \| `synced` |
| timestamp | Date |

### Dexie: `user_settings`

| Field | Type |
|---|---|
| id | string, e.g. `"config"` |
| model_downloaded | boolean |
| storage_persisted | boolean |
| cloud_fallback_accepted | boolean – true once the user declined the local helper |

### Cloud: `user_activities`

| Field | Type |
|---|---|
| id | UUID |
| user_id | UUID, FK to auth user |
| activity | text |
| distance | numeric |
| unit | text |
| duration_minutes | integer |
| logged_at | timestamp |

**Recommended additions:** a client-generated UUID on each local record and a unique constraint on the cloud table so retried syncs never create duplicates; RLS policy `user_id = auth.uid()`.

## 6. Implementation Phases (review gate after each)

### Phase 1 – Foundation
- Scaffold/extend the Vite web app, Tailwind accessibility tokens, Workbox service worker.
- Dexie schema (`activities`, `user_settings`) and a settings helper module.
- Stop and review.

### Phase 2 – Capture and UI
- Web Speech capture with pulsing mic, live transcript, permission and unsupported-browser handling, typing fallback.
- Dashboard (today's and recent logs), confirmation card, Helper Download popup (UI only).
- Stop and review.

### Phase 3 – Local helper
- Web Worker running Transformers.js: load, progress events, extract JSON, validate against schema.
- Download flow with progress, `navigator.storage.persist()`, settings updates, resume on interrupted download.
- Stop and review.

### Phase 4 – Cloud and sync
- Backend endpoint for Gemini structured extraction (auth required, rate limited, API key server-side only).
- Cloud tables with RLS, sync engine on `online` event, status transitions, retry with backoff.
- Stop and review.

### Phase 5 – Hardening
- Accessibility audit (screen reader, keyboard, 200% zoom), cross-browser tests, offline tests, error and empty states, privacy copy.

## 7. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Web Speech API is not in every browser (weak in Firefox) and Chrome may send audio to Google's servers. | Feature-detect, show typing fallback; do not claim audio never leaves the device – say only that the extracted activity is processed on-device. |
| A 77M-parameter model may extract numbers/units unreliably. | Rule-based parser cross-checks the output; confirmation card catches errors; test on a phrase set before shipping; keep cloud as upgrade path. |
| 80MB download on mobile data; storage may be evicted or denied. | Warn on mobile data, show progress, allow resume, re-prompt gracefully if the model is missing; `persist()` may be refused – handle it. |
| iOS Safari limits storage and background sync. | Sync on page open and `online` event, not only the service worker. |
| Duplicate or lost records during sync. | Client UUIDs, idempotent upserts, status changes only after server confirms. |
| Health-adjacent data privacy. | RLS, HTTPS, no raw audio stored, clear privacy text, delete-my-data option. |

## 8. Open Decisions for Review

1. **Frontend stack:** the existing site is vanilla JS + Vite + Tailwind with no React. Keep it, or migrate to React for this feature?
2. **Backend:** use our existing Flask backend (auth, rate limiting, Postgres) for the Gemini endpoint and storage instead of a separate serverless route plus Supabase? Recommended, to avoid two auth systems.
3. **Install prompt:** installable web app wanted, or plain website only?
4. **Languages:** English only at launch, or more?
5. **Activity scope:** free-form (walking, yoga, gym…) or a fixed list?

## 9. Definition of Done

- User can log a workout by voice or typing in under 10 seconds, online or offline.
- Every log is confirmed by the user before it counts.
- Records reach the cloud exactly once after connectivity returns.
- Passes accessibility checks and works on current Chrome, Edge, Safari and Android/iOS browsers.
