# Frontend-only improvements — technical plan (zero backend changes)

Scope: only items that need **no new endpoint, no schema change, no backend code touched at all** —
everything here is either a new arrangement of data the backend already returns, or pure client-side
state. This is a planning document only; nothing in this file has been implemented yet.

Checked against the actual current code (not assumed) before including anything below.

---

## Item 0 — Ruled OUT: don't re-add 1-month / 1-year heatmap tabs

The mockup review flagged our heatmap only offering 3M/6M/12M vs. the mockup's 1M/3M/6M/1Y as a
possible gap. Checked `frontend/src/main.js:263-266` — **1M was already tried and deliberately
reverted**:

```js
let activityPeriodMonths = 3; // default tab — 1M made cells so big (to fill
// the width with only ~5 columns) that it blew up the card's height instead
```

12M is already functionally identical to the mockup's "1Y" (same data, different label) — not a
real gap, just a naming difference not worth touching. Not including this in the plan below;
re-adding 1M would need a real fix to `HEATMAP_MAX_CELL` sizing first, which is a layout bug-fix
task, not a free win.

---

## Item 1 — "Most active day" insight line on the heatmap card

**What:** A small computed line under the heatmap, e.g. *"You're most active on Thursdays"* —
mirrors the mockup's static "Peak days: Thu & Sat" copy, but real.

**Why zero-backend:** The data already sits in the browser. `loadHome()`
(`frontend/src/main.js:494-499`) already fetches `GET /v1/dashboard/trend?days=365` once into
`activityYearData` — a full year of `{date, count}`. No new fetch needed.

**Implementation:**
- New function `mostActiveWeekday(daily)` in `main.js`: group `activityYearData` by JS
  `new Date(d.date).getDay()`, sum `count` per weekday, return the weekday(s) with the highest
  total (tie → list both, e.g. "Thu & Sat", matching the mockup's own phrasing for a tie).
- Call it once after `activityYearData` is populated in `loadHome()` (right after line 499), write
  the result into a new `<p id="h-heatmap-insight">` under the heatmap grid in `index.html`.
- Edge case: fewer than ~2 weeks of data (new account) → show nothing rather than a misleading
  insight from 1-2 data points. Guard: skip rendering if `activityYearData.filter(d => d.count >
  0).length < 10`.

**Files touched:** `frontend/src/main.js`, `frontend/index.html` (one new element).

**Effort:** small — one pure function, no new state, no new network call.

---

## Item 2 — "Today's top pick" featured exercise card

**What:** A single highlighted card above the regular suggestions list, surfacing the single most
relevant not-yet-done exercise for today — adapts the mockup's "Morning Run" hero banner concept,
without the running/km framing (which doesn't fit this app — see prior scope review).

**Why zero-backend:** `GET /v1/dashboard/summary` (`main.js:495`) already returns
`suggestions.all_items`, already sorted by `usefulness_rank` then by completion status
(`app/profile/service.py` `suggestions_today`, `items.sort(key=lambda i: (i["completed"],
i["usefulness_rank"], i["priority_order"]))`). The featured card is just `items[0]` — the first
not-completed item — rendered bigger, nothing new to fetch.

**Implementation:**
- In `loadHome()`, after `HOME_ITEMS = items;` (line 505): find `const featured =
  items.find(i => !i.completed);` (falls back to `undefined` if everything's already done today —
  render nothing in that case, not an empty/broken card).
- New `renderFeaturedCard(i)` function: larger card with activity name, prescription
  (`i.prescription`), caution note if present (`i.caution`), and a "Mark done" button that calls
  the **existing** log action (the same function the regular cards already use for a prescribed
  quick-log — check `renderCard`'s own log button handler and reuse it verbatim, not a new
  endpoint call).
- Insert the rendered featured card into a new container at the top of the home screen (above the
  regular suggestions grid) in `index.html`.
- When `featured` is `undefined` (nothing left to do today), show nothing — no "all done!" filler
  needed since the regular suggestions list already communicates that state.

**Files touched:** `frontend/src/main.js`, `frontend/index.html` (one new container + card
template).

**Effort:** small-medium — mostly a rendering/layout task; reuses the existing log call, not a new
one.

---

## Item 3 — Light/dark theme toggle (Settings → Appearance)

**What:** Wire up the currently-dead "Appearance" row in Settings (mockup shows it as a static
"Sage Light" label with no handler) into a real light/dark toggle.

**Why zero-backend:** A display preference with no cross-device sync requirement is a pure
client-side concern — `localStorage`, never a server round-trip.

**Important scope note, flagging before any work starts:** this is **zero backend cost but NOT a
trivial frontend task**. Checked `frontend/index.html` — there is currently **no dark-mode
scaffolding at all**: no `data-theme` attribute, no `prefers-color-scheme` media query, no
alternate color tokens defined anywhere. Every color in the app today is a single hardcoded
Tailwind/CSS-variable value. Doing this properly means:
- Auditing every color token currently used (surface, on-surface, primary-container, etc. — the
  Material-style token names already in use throughout `index.html`) and defining a dark
  counterpart for each.
- Adding a `data-theme="dark"` toggle mechanism and redefining those tokens under it.
- Checking every screen still reads correctly (contrast, the glass-card/blur effects used
  elsewhere in this app's design) — not just the Settings screen itself.

**Recommendation:** worth doing, but should be scoped and estimated as its own small design pass,
not bundled in with Items 1-2 above (which are each under an hour of real work). Suggest treating
this as a 4th item to schedule separately once 1-2 are done, rather than blocking them on it.

**Files touched (if/when done):** `frontend/index.html` (color tokens + toggle), `frontend/src/main.js`
(toggle handler + `localStorage` read/write on load).

---

## Suggested order

1. Item 1 (most-active-day insight) — smallest, fully self-contained, good warm-up.
2. Item 2 (featured exercise card) — most user-visible value for the effort.
3. Item 3 (theme toggle) — real but bigger scope; do as its own pass.

Nothing here touches `app/`, `migrations/`, or any CSV — purely `frontend/` changes, testable with
`npm run build` plus manually exercising the dashboard, same verification pattern used for every
other frontend change this session.
