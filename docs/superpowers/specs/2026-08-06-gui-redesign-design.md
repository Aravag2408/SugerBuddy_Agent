# GUI Redesign — Design

## Context

The current `static/index.html` is a functional but purely utilitarian GUI: one textarea reused
for every turn (event description, 10 questionnaire answers typed as free text, the optional
follow-up answer), a scrolling chat-style transcript log, and raw `<details>` blocks for the
per-step technical trace. It works and is deployed, but the user wants a visually polished,
family-facing redesign, driven by three mockup screens she provided: the 10-question check-in as
tappable Yes/No cards with a progress bar, the single adaptive follow-up question as a styled
free-text card, and a redesigned "message to the teen" screen with a new confirmation step.

This is a frontend-only redesign of `static/index.html`. No backend, API contract, or pipeline
change is in scope — `agent_pipeline.py`, `api/index.py`, and the conversation-state marker
mechanism are untouched.

## Course requirement check

The course PDF (`Project.pdf`, GUI Requirements section) mandates: *"Display the full steps trace
(steps), including: module, prompt, Response."* This is **required**, not optional. The redesign
keeps the technical trace visible on every screen that follows an `/api/execute` call — restyled
to match the new theme and tucked into a collapsible section — rather than removing it.

## Trade-off flagged during self-review

The course PDF lists, under *optional* GUI requirements ("only if supported by your agent"):
"Support back-and-forth interaction" and "Display conversation history in the UI." SugarBuddy does
support back-and-forth (the one adaptive follow-up question), and the currently deployed GUI shows
a full accumulating chat log. This redesign replaces that log with single-focused screens per the
user's own mockups, which show one step at a time rather than a running history. Since this
requirement is explicitly optional, and the single-screen model is what the user specifically
asked for, this is treated as an accepted, deliberate trade-off rather than a gap — noted here so
it's a visible decision, not a silent one.

## Decisions made during brainstorming

- **Screen model, not chat log.** The mockups show one focused screen at a time, not an
  accumulating transcript. The redesign replaces the scrolling `#conversation-log` with five
  discrete screens, shown one at a time via a `showScreen(id)` toggle: **Intro → Questions →
  (optional) Follow-up → Summary/Parent-decision → Teen-message**.
- **No backend change.** `questionnaire.parse_answers` already accepts `"כן"`/`"לא"` as well as
  `Y`/`N` in its numbered-list regex, so the Yes/No buttons just assemble the same
  `"1. כן 2. לא ..."` formatted string the backend already expects. The full transcript-marker
  round-trip protocol is unchanged.
- **10-question screen**: all 10 questions rendered together as scrollable cards (not one at a
  time), each with an emoji, a numbered badge, and two large Yes/No buttons. A progress line
  ("ענית על N מתוך 10 שאלות") and progress bar update as questions are answered. A "המשך" button
  appears/enables only once all 10 are answered.
- **Follow-up screen**: kept as free text (the question itself is LLM-generated and open-ended,
  not necessarily yes/no), styled per the mockup — bordered card with the question, a required
  textarea capped at 500 characters with a live counter, and a Send button. The mockup's "חזרה →"
  link is **dropped** — the conversation state has no notion of rewinding to a prior turn, so a
  working back button isn't possible without a design not yet under discussion.
- **New "did you follow the recommendation?" step**: purely client-side, no logging, no backend
  call — consistent with the existing parent-decision relay, which has always been plain-text
  pass-through with no server involvement.
- **No home/reset icon.** Removed per feedback — redundant with the existing end-of-flow reset.
- **Two screens have no mockup and are designed here, in the same visual language**: the intro
  screen (event description) and the summary/parent-decision screen (agent's response + the
  parent's decision input). Both follow section B below.

## A. Shared visual theme

- **Palette** (CSS custom properties, easy to retune):
  - `--color-primary: #7a1f3d` (deep burgundy — headings, primary buttons, selected states)
  - `--color-primary-dark: #5c1730` (hover/active)
  - `--color-card: #fdf6fb` (card background, near-white lavender)
  - `--color-card-alt: #f3ecfa` (secondary card fill, e.g. unselected button)
  - `--color-border: #e8dcef`
  - `--color-text: #2a1a22`
  - `--color-text-muted: #6b5c66`
- **Background**: a fixed, non-interactive decorative layer behind all content — a soft
  purple → peach → pink gradient wash with a few large, blurred, semi-transparent circles
  (pure CSS `radial-gradient` shapes + `filter: blur()`, `position: fixed`, `z-index: -1`,
  `pointer-events: none`). No external images, so the page stays fully self-contained.
- **Cards**: rounded corners (~16px), soft `box-shadow`, generous padding, `--color-card`
  background.
- **Direction**: `dir="rtl"` set once on `<html>` (all user-facing copy is Hebrew), replacing the
  current per-element `direction: auto`.
- **Buttons**: pill/rounded-rect. Primary action buttons are solid `--color-primary` with white
  text. Yes/No question buttons are `--color-card-alt` with a border when unanswered, and switch
  to solid `--color-primary` with white text once selected (re-clickable to change the answer
  before continuing).

## B. Screens

1. **Intro** (no mockup — designed here to match): heading, one-line subtitle, a textarea
   ("תארי את אירוע הסוכר..."), and a primary "התחל" button. Calls `/api/execute` with the raw
   text as `prompt`.
2. **Questions** (matches mockup 1): heading "כמה שאלות קצרות", subtitle, progress line + bar,
   then all 10 question cards in a scrollable list — each with an emoji, numbered badge, question
   text, and Yes/No buttons. Emoji assignment (first 3 match the user's mockup exactly; the rest
   chosen to fit):
   1. ⏱️ אכלת משהו בתוך השעתיים האחרונות?
   2. 🧮 האם הזנת כמות מדוייקת של פחמימות או בערך?
   3. 👟 רצת, קפצת, או עשית שיעור ספורט או אימון ב-4 השעות האחרונות?
   4. 😤 מישהו הרגיז אותך או שהיית בלחץ גדול בחצי השעה האחרונה?
   5. 💧 שתית לפחות 4 כוסות מים במהלך היום?
   6. ☀️ האם היית בחוץ במזג אוויר חם מאוד בחצי השעה האחרונה?
   7. 💉 החלפת משאבה או לקחת מנת תיקון (או פחמימות מהירות להיפו) ב-3 השעות האחרונות?
   8. 📱 האם היית צמודה לטלפון הנייד בשעה האחרונה, והאם בדקת שהחיישן והמשאבה מחוברים חזק לעור?
   9. 🍎 האם אכלת ארוחות מדוייקות היום?
   10. 🩸 האם עשית בדיקה באצבע או כיול לאחרונה?

   "המשך" button appears once all 10 are answered; formats answers as
   `"1. כן 2. לא ..."` and calls `/api/execute` with the transcript + that line.
3. **Follow-up** (matches mockup 2, minus "חזרה"): shown only if the response contains the
   `SUGARBUDDY_CONTEXT` marker after the questions screen's call. Bordered card showing the
   agent's question, a required textarea (500-char cap + live counter), Send button.
4. **Summary / parent decision** (no mockup — designed here): shown once a response arrives
   *without* the marker. A card renders the agent's final response text (the parent summary).
   Below it, a "החלטת ההורה" textarea and a "שלח לנער/ה" button — same plain-text, client-only
   relay as today, just restyled.
5. **Teen message** (matches mockup 3): shows the parent's typed text in a bordered highlight
   card, then "ביצעת את ההמלצה?" with two selectable options ("עשיתי" / "לא עשיתי", client-side
   state only, nothing sent anywhere), and a "המשך לסיום האירוע" button that resets everything
   back to the Intro screen.

Every screen reached after an `/api/execute` call (Questions, Follow-up, Summary) includes a
collapsible "פרטים טכניים" section rendering that call's `steps` (module / system prompt / user
prompt / response) — same content as today's `<details>` blocks, restyled, satisfying the course's
steps-trace requirement without cluttering the main screen.

## C. Data flow / state machine

Purely a presentation-layer change. JS keeps the same `transcript` string and marker round-trip
logic as today. New local state: `currentTranscript`, an `answers` array of 10 (`null` until
answered), and `lastSteps` (the most recent call's `steps`, rendered into whichever screen appears
next). A `showScreen(id)` helper hides all `.screen` elements and displays one. Screen transitions:

- Intro → call API → always returns the marker (per `run_pipeline`, turn 1 always asks the
  questionnaire) → show Questions, seed `lastSteps`.
- Questions (all 10 answered) → call API → marker present → show Follow-up; marker absent → show
  Summary. Either way, update `lastSteps`.
- Follow-up → call API → per `run_pipeline`, the `followup_sent` stage always finalizes → show
  Summary, update `lastSteps`.
- Summary → "Send to teen" → no API call (client-side only) → show Teen message.
- Teen message → "המשך לסיום האירוע" → reset all state → show Intro.

Error handling is unchanged in substance: a non-2xx or `status: "error"` response surfaces in a
visible error box on the current screen (restyled to match the theme) rather than advancing.

## D. Testing

Manual browser verification with `fetch` mocked/stubbed at the network layer (no real LLM calls),
covering: the full 5-screen path with a follow-up, the path without a follow-up, one Yes/No answer
changed before continuing, and the error-box path on a mocked failed call. No backend or Python
test changes are needed since the API contract is untouched.
