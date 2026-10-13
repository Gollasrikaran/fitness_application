# Child Motivational Companion — Implementation Plan

Status: planning only, nothing built yet. Captures the decisions already made in discussion, and
what's still open for the build phase itself.

---

## 1. What this is

A motivational chat + task/reward feature for children/teens, living entirely under a parent's own
account. Not an emotional companion — a coach that encourages exercise, study, sleep, and meals.
Fully visible to the parent. No independent child login.

## 2. Decisions already made

- **Parent-owned accounts only.** No child self-registration, no age self-report, no voice-based
  age guessing. A child profile is created and owned by an authenticated parent — this sidesteps
  age-verification entirely rather than trying to solve it.
- **Consent before activation.** A child profile cannot send/receive any chat or task content
  until the parent has explicitly consented, with the consent itself logged (what was shown,
  when).
- **Data use promise**: child conversation data is used only for that child, never for model
  training, and auto-deleted after 30 days.
- **Health gate, not a disclaimer-only.** At setup: "Is your child healthy?" — if not, the profile
  is blocked from the feature with a "please consult a doctor" message, mirroring this app's
  existing adult-side pattern of routing complex/risky cases to a doctor instead of guessing.
- **Rewards are parent-defined and optional.** No parent-set reward → default tasks are simple and
  unscored (e.g. "go for a bike ride," no distance/time target).
- **Not a companion.** No persistent "personality," no relationship/bonding memory, no romantic or
  emotionally dependent framing — motivational tone only.

## 3. Data model (new, additive — doesn't touch the existing adult-side tables)

| Entity | Purpose |
|---|---|
| `ChildProfile` | Name, age-band (for task calibration only, not a legal gate), health-gate answer, linked to the owning parent's `user_id`. |
| `ChildConsent` | What consent text was shown, when, recorded the moment a parent activates a child profile — same pattern this app already uses for safety-override consent records. |
| `ChildTask` / `ChildReward` | Parent-defined task + optional reward text, or a reference to one of the small built-in default tasks. |
| `ChildConversationLog` | Chat history, parent-visible, auto-deleted after 30 days via a scheduled cleanup job (same pattern as the existing refresh-token reaper). |

## 4. Conversation design — the part that needs the most care

- A fixed, narrow system prompt: motivational encouragement about exercise/study/sleep/meals and
  general age-appropriate conversation. Explicitly excludes relationship language, role-play, and
  anything emotionally dependent.
- **Hard refusal list**: self-harm, abuse, violence, relationships, anything inappropriate — the AI
  does not attempt to engage with these at all. Instead it gives a fixed, safe, supportive response
  and the conversation is flagged (see below).
- No long-term "memory"/personality state carried between sessions — removes the exact mechanism
  that caused real documented harm in companion-style products elsewhere.

## 5. Crisis / disclosure handling (needs its own dedicated design pass before launch)

- Every child message is checked for concerning content (self-harm, abuse, bullying, distress)
  *before* the AI is allowed to respond normally.
- A match pauses the normal conversation, shows a fixed supportive message, and **actively
  notifies the parent** — not just "it'll be in the visible history," a real alert.
- Needs a real fallback resource (e.g. a helpline reference) for situations where the parent isn't
  reachable or is part of the problem — this can't rely on "tell a parent" as the only path.
- Starting point: a rules/keyword first pass; a proper safety-classification model before any real
  launch. This item alone should get a dedicated review before going live — flagging it here so it
  doesn't get compressed into "just add a filter."

## 6. Task & reward engine

- Parent can define: task text + (optional) reward text.
- No parent-defined task → offer from a small built-in list of simple, unscored tasks (e.g. "go
  for a walk," "go for a bike ride") — no numeric targets, unlike the adult program's prescribed
  sets/distance.
- Completion is self-reported by the child (a single "I did it" tap) — trusted, not verified,
  consistent with how this app already treats adult activity logs.
- Reward only displays if the parent configured one for that specific task.

## 7. Tech approach

- Reuse the existing LLM integration pattern (same provider already used for the adult rehab
  chatbot) but as a **fully separate prompt/config** — never sharing context, history, or system
  prompt with the adult chatbot.
- Reuse existing auth/session infrastructure — a child profile is a new kind of resource under an
  already-authenticated parent session, not a new login system.
- Content moderation runs as its own pass, separate from the main chat call, on both the child's
  input and the AI's output before either is shown.

## 8. Before this goes live — a short checklist

- [ ] Legal review of the consent screen wording and the 30-day retention promise (DPDP Act).
- [ ] Crisis-escalation path tested against real adversarial scenarios, not just happy-path demos.
- [ ] Confirm zero data/context sharing between the child feature and the adult rehab chatbot.
- [ ] Start with a small, manually-reviewed beta (sample conversations checked by a person) before
      any wider release.

## 9. Still open — to decide during build, not blockers to starting

- Exact consent screen wording (legal should word this, not engineering).
- Which crisis-detection approach ships first (keyword rules vs. a dedicated model) — fine to start
  simple and improve, as long as it's never silently skipped.
- Whether age-bands need to be finer than "child vs. teen" for task calibration (a 6-year-old and a
  15-year-old need very different defaults).

---

*Nothing in this plan has been implemented. Next step, when ready: pick a first slice (likely:
ChildProfile + consent flow + health gate, with chat and tasks following after) and scope that as
its own build.*
