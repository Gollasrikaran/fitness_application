# ViTAinspire — Feature Overview

A plain-language summary of what the app already does, and what's planned next.
Feature names and what they do for the user — kept light on technical detail.

---

## ✅ Already Built

### Account & Login
- **Sign up / Log in / Log out**
- **Change password**
- **Forgot password** flow (the screen exists; actually emailing the reset code is a separate planned piece — see below)
- **Delete account**

### Getting Started (Onboarding)
- Age, primary goal (health / fitness / flexibility / habit), and experience level questions
- **Health condition selection** — a list of 28 conditions, written in plain, commonly-used Indian-English terms (e.g. "Slip disc," "Sugar not under control," "BP under control") instead of clinical names
- Conditions needing a doctor's attention (heart problems, pregnancy, uncontrolled diabetes/BP, etc.) are routed to a **"please see a doctor first"** message instead of exercise suggestions

### Safety System
- Every exercise is checked against every condition a user has, with one of three outcomes: **safe**, **safe with a caution note**, or **not recommended**
- If a user has more than one condition, the strictest applicable rule always wins
- A user can still choose to add a "not recommended" exercise anyway, but only after seeing a clear warning naming the condition and reason — and that choice is recorded

### Personalized Exercise Program
- A starting program is built automatically from the user's conditions
- **Experience-based pacing** — beginners see 4 exercises, growing to 5, 7, 9, and finally the full list as experience increases
- **"Most useful first" personalized ordering** — exercises are ranked per condition by how useful they actually are for that condition (not just a generic order), and a user with multiple conditions sees whichever exercise is most useful for *any* of them first
- Users can browse the full exercise catalogue and add/remove exercises themselves
- Automatic weekly progression (gradually increasing reps/duration as a user keeps up), plus progression the chatbot can offer mid-conversation

### Activity Logging
- Log any prescribed exercise (sets, reps, hold time, distance, or duration depending on the exercise)
- **Custom exercises** — a user can track something of their own that isn't in the official list
- Reliable logging that won't double-count entries even on a flaky connection

### Dashboard
- Stat cards: total workouts, this month, current streak, best streak
- **Activity heatmap** (3/6/12-month views) showing daily activity at a glance
- **"You're most active on [day]"** insight, computed from a user's own history
- **"Today's Top Pick"** — a highlighted card spotlighting the single most useful exercise left to do today, with a one-tap "do it now" log action

### Rehab & Pain Chatbot
- Ask questions about pain, recovery, or exercise guidance in plain language
- Answers are grounded only in reviewed medical reference material and the user's own approved exercise list — it will never invent an exercise or suggest medication/surgery
- **Daily question limit**, shown to the user, so usage stays sustainable
- Can suggest switching the day's program based on the conversation (with a one-tap confirm), and can recognize when a user mentions a new condition mid-chat

### Video Library
- Curated demonstration videos and step-by-step instructions for exercises

### Notifications screen
- Present in the app, honestly marked "coming soon" rather than faking a feature that isn't built yet

---

## 🚧 Planned Next

### Exercise Workout Player
A guided, one-exercise-at-a-time session screen — tap through today's exercises with a built-in rest timer between sets, a running session clock, and a completion summary at the end. Designed to track real session history (start/finish time, how many exercises completed), not just individual logs.

### Tap-a-day activity detail
Tapping a specific day on the activity heatmap will show exactly what was done that day, instead of just a hover tooltip.

### Dark mode / theme toggle
A light/dark appearance option in Settings.

### Notifications & Reminders
Real push/email reminders — workout reminders, weekly progress summaries. Not started yet; today's "coming soon" screen is a placeholder for this.

### Email delivery
Verifying a new account by email, and emailing password-reset codes. Right now these are stand-ins: a password reset must be done manually by an admin. **This is a deliberate, known gap — not scheduled yet.**

### Full account data removal
Deleting an account currently deactivates it; fully erasing the underlying data on deletion is a planned follow-up.

### Multi-condition interaction safety
Handling the case where two conditions are individually fine with an exercise, but *together* make it risky — a combined-conditions safety check, designed conceptually but not yet built.

### Water / hydration tracking
Logging daily water intake, with a visible progress-toward-goal indicator.

### Sleep tracking
Logging sleep duration, with progress toward a daily sleep goal.

### Meal & calorie tracking
Logging meals (breakfast/lunch/dinner) and daily calorie intake.

### Frictionless Dietary Logging
Take a picture of a plate of food and have AI estimate the ingredients, calories, and macros automatically — no manual entry needed.

### Body weight tracking
Logging body weight over time.

### Child Motivational Companion
A parent-owned chat and task/reward feature for children/teens — motivates exercise, study, sleep, and meals through simple conversation and parent-set rewards. Fully visible to parents, with no independent child login and no emotional-companion framing. Detailed plan already written; several safety/legal pieces (consent flow, crisis-disclosure handling) need dedicated design work before this is built.

---

## 📋 Seen in the new design (vitainspire/Frontend) — not yet decided

Reviewed the new design repo in full. A few real, in-scope ideas showed up there that aren't
in either list above yet — flagging them so they don't get lost, not committing to build them yet:

- **"Log a recovery/rest day" quick action in chat** — a one-tap button in the chatbot to log a
  rest day, instead of only being able to log an actual exercise.
- **Weekly activity chart** — a day-by-day (Sun–Sat) breakdown of this week's activity, as its own
  view separate from the long-range heatmap.
- **"Top X% of users" activity comparison badge** — comparing one user's consistency against
  everyone else's. Bigger decision than it looks: needs us to decide whether cross-user comparison
  is something we want in a medical/rehab app at all, not just a quick add.
- **Time-of-day adaptive dashboard banner** — the top banner changes its photo/message between
  morning and evening. Purely cosmetic; low priority.

---

*This is a living summary — update it as features move from "planned" to "built."*
