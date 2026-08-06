# GUI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `static/index.html` from a free-text chat log into a 5-screen wizard (Intro →
Questions → optional Follow-up → Summary → Teen message) with tappable Yes/No question cards and
a maroon/gradient visual theme, per `docs/superpowers/specs/2026-08-06-gui-redesign-design.md`.

**Architecture:** Single self-contained HTML file (inline CSS + JS, no build step, no framework —
matching the project's existing GUI approach). One `<section class="screen">` per wizard screen,
toggled via a `showScreen(name)` JS helper; only one screen has `class="screen active"` at a time.
No backend, API, or Python changes — the same `/api/execute` contract and
`SUGARBUDDY_CONTEXT` marker round-trip protocol are reused unchanged.

**Tech Stack:** Plain HTML/CSS/JS (no dependencies), served by the existing FastAPI `GET /` route
in `api/index.py` (unchanged — it already reads `static/index.html` per request).

## Global Constraints

- Frontend-only change. Do not modify `api/index.py`, `agent_pipeline.py`, `questionnaire.py`,
  `conversation_state.py`, or any test under `tests/`.
- `questionnaire.parse_answers` (see `questionnaire.py:20`) accepts `Y`/`N`/`Yes`/`No`/`כן`/`לא`
  per numbered line via regex `(\d+)\.\s*(Y|N|Yes|No|כן|לא)\b` — the Yes/No buttons must produce
  lines of the exact form `"1. כן"` / `"1. לא"` (number, period, space, then exactly `כן` or `לא`).
- The course PDF requires the full `steps` trace (module, prompt, response) to remain visible in
  the GUI — every screen reached after an `/api/execute` call must keep a collapsible technical
  section showing that call's `steps`.
- Theme tokens (from the spec): `--color-primary: #7a1f3d`, `--color-primary-dark: #5c1730`,
  `--color-card: #fdf6fb`, `--color-card-alt: #f3ecfa`, `--color-border: #e8dcef`,
  `--color-text: #2a1a22`, `--color-text-muted: #6b5c66`.
- `dir="rtl"` is set once on `<html>` — all user-facing copy is Hebrew.
- No home/reset icon (removed per user feedback) — the only way back to the Intro screen is the
  "המשך לסיום האירוע" button at the very end of the flow.
- Exact spacing/alignment in the CSS below is a first draft, not gospel — the user supplied 3
  reference screenshots (10-question screen, follow-up screen, teen-message screen); during
  manual verification, compare the rendered page against those images and adjust padding/gaps/
  alignment to match, without changing the underlying structure or logic.

## Manual verification technique (used by every task below)

There is no JS test runner in this project (Python + pytest only), and GUI changes are verified
manually per this project's established pattern. To verify without spending real LLM budget,
override `fetch` in the browser DevTools console before clicking through a scenario:

```js
window.fetch = async (url, opts) => {
  const body = JSON.parse(opts.body);
  console.log("SENT PROMPT:", JSON.stringify(body.prompt));
  return {
    ok: true,
    json: async () => (window.__mockResponse),
  };
};
```

Then before each click that triggers a call, set `window.__mockResponse` to the canned response
for that scenario (exact payloads are given in each task below). Start the app locally with
`uvicorn api.index:app --reload` and open `http://127.0.0.1:8000/`.

---

### Task 1: Theme shell, Intro screen, Questions screen

**Files:**
- Modify (full rewrite): `static/index.html`

**Interfaces:**
- Produces: `showScreen(name)` (name is one of `"intro"`, `"questions"`, `"followup"`,
  `"summary"`, `"teen"`), `stripMarker(text)`, `renderTechTrace(container, steps)`,
  `callExecute(promptText)` (returns the parsed JSON body), module-level `transcript` (string)
  and `answers` (array of 10, `true`/`false`/`null`) variables, `QUESTIONS` (array of
  `[emoji, text]` pairs, in the exact order from `questionnaire.py:8-17`).
- Consumes: nothing (first task).

- [ ] **Step 1: Write the full replacement file**

Replace the entire contents of `static/index.html` with:

```html
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SugarBuddy</title>
<style>
  :root {
    --color-primary: #7a1f3d;
    --color-primary-dark: #5c1730;
    --color-card: #fdf6fb;
    --color-card-alt: #f3ecfa;
    --color-border: #e8dcef;
    --color-text: #2a1a22;
    --color-text-muted: #6b5c66;
  }
  * { box-sizing: border-box; }
  body {
    font-family: system-ui, sans-serif;
    margin: 0;
    padding: 2rem 1rem;
    color: var(--color-text);
    line-height: 1.5;
    min-height: 100vh;
  }
  .bg-decoration {
    position: fixed;
    inset: 0;
    z-index: -1;
    pointer-events: none;
    background: linear-gradient(135deg, #efe3f7 0%, #fbe9df 50%, #fbe3ec 100%);
    overflow: hidden;
  }
  .bg-decoration::before, .bg-decoration::after {
    content: "";
    position: absolute;
    border-radius: 50%;
    filter: blur(60px);
    opacity: 0.55;
  }
  .bg-decoration::before { width: 420px; height: 420px; background: #caa6e0; top: -120px; left: -100px; }
  .bg-decoration::after { width: 380px; height: 380px; background: #f7b98c; bottom: -100px; right: -80px; }
  .app { max-width: 700px; margin: 0 auto; }
  .screen { display: none; }
  .screen.active { display: block; }
  h1.screen-title { color: var(--color-primary); font-size: 1.6rem; margin: 0 0 0.25rem; }
  .screen-subtitle { color: var(--color-text-muted); margin: 0 0 1.25rem; }
  .card {
    background: var(--color-card);
    border-radius: 16px;
    box-shadow: 0 4px 18px rgba(122, 31, 61, 0.08);
    padding: 1.25rem 1.5rem;
    margin-bottom: 1rem;
  }
  textarea {
    width: 100%; min-height: 5rem; font-family: inherit; font-size: 1rem;
    padding: 0.75rem; border-radius: 10px; border: 1px solid var(--color-border);
    resize: vertical;
  }
  textarea:focus { outline: none; border-color: var(--color-primary); }
  .btn-primary {
    display: block; width: 100%; border: none; border-radius: 10px;
    padding: 0.75rem 1.5rem; font-size: 1rem; font-weight: 600; cursor: pointer;
    background: var(--color-primary); color: #fff; margin-top: 0.75rem;
  }
  .btn-primary:hover { background: var(--color-primary-dark); }
  .btn-primary:disabled { background: #d9c3cd; cursor: not-allowed; }
  .progress-line { font-size: 0.95rem; margin-bottom: 0.5rem; }
  .progress-bar-track {
    background: var(--color-card-alt); border-radius: 999px; height: 8px; overflow: hidden; margin-bottom: 1.5rem;
  }
  .progress-bar-fill {
    background: var(--color-primary); height: 100%; border-radius: 999px; transition: width 0.2s ease; width: 0%;
  }
  .question-card { display: flex; flex-direction: column; gap: 0.75rem; }
  .question-header { display: flex; align-items: center; gap: 0.5rem; font-weight: 600; font-size: 1.05rem; text-align: right; }
  .question-badge {
    background: #f5d9df; color: var(--color-primary); border-radius: 50%;
    width: 1.75rem; height: 1.75rem; display: flex; align-items: center; justify-content: center;
    font-size: 0.85rem; font-weight: 700; flex-shrink: 0;
  }
  .question-buttons { display: flex; gap: 0.75rem; }
  .yn-btn {
    flex: 1; padding: 0.9rem; border-radius: 10px; border: 1px solid var(--color-border);
    background: var(--color-card-alt); color: var(--color-text); font-size: 1rem; font-weight: 600; cursor: pointer;
  }
  .yn-btn.selected { background: var(--color-primary); color: #fff; border-color: var(--color-primary); }
  details.tech-trace { margin-top: 1.5rem; }
  details.tech-trace > summary { cursor: pointer; font-weight: 600; color: var(--color-text-muted); font-size: 0.9rem; }
  details.tech-trace .step-block { margin-top: 0.75rem; }
  details.tech-trace .step-block summary { color: var(--color-primary); cursor: pointer; }
  details.tech-trace pre {
    white-space: pre-wrap; background: var(--color-card-alt); padding: 0.75rem; border-radius: 8px;
    direction: auto; font-size: 0.85rem;
  }
  #error-box {
    display: none; color: var(--color-primary); background: #fbe4ea; border: 1px solid var(--color-primary);
    border-radius: 10px; padding: 1rem; margin-bottom: 1rem;
  }
</style>
</head>
<body>
<div class="bg-decoration"></div>
<div class="app">
  <div id="error-box"></div>

  <section id="screen-intro" class="screen active">
    <h1 class="screen-title">SugarBuddy</h1>
    <p class="screen-subtitle">ספרי לנו מה קרה עם הסוכר, ונעזור להבין ביחד.</p>
    <div class="card">
      <textarea id="intro-input" placeholder="לדוגמה: הסוכר קפץ ל-260 ועולה מהר"></textarea>
      <button id="intro-button" class="btn-primary">התחל</button>
    </div>
  </section>

  <section id="screen-questions" class="screen">
    <h1 class="screen-title">כמה שאלות קצרות</h1>
    <p class="screen-subtitle">ענה על כל השאלות כדי שנוכל להבין טוב יותר מה קרה.</p>
    <p class="progress-line"><span id="progress-count">0</span> מתוך 10 שאלות נענו</p>
    <div class="progress-bar-track"><div id="progress-bar-fill" class="progress-bar-fill"></div></div>
    <div id="questions-list"></div>
    <button id="questions-continue-button" class="btn-primary" disabled>המשך</button>
    <div id="questions-tech-trace"></div>
  </section>
</div>

<script>
  const QUESTIONS = [
    ["⏱️", "אכלת משהו בתוך השעתיים האחרונות?"],
    ["🧮", "האם הזנת כמות מדוייקת של פחמימות או בערך?"],
    ["👟", "רצת, קפצת, או עשית שיעור ספורט ואימון ב-4 השעות האחרונות?"],
    ["😤", "מישהו הרגיז אותך או שהיית בלחץ גדול בחצי השעה האחרונה?"],
    ["💧", "שתית לפחות 4 כוסות מים במהלך היום?"],
    ["☀️", "האם היית בחוץ במזג אוויר חם מאוד בחצי השעה האחרונה?"],
    ["💉", "החלפת משאבה או לקחת מנת תיקון (או פחמימות מהירות להיפו) ב-3 השעות האחרונות?"],
    ["📱", "האם היית צמודה לטלפון הנייד בשעה האחרונה, והאם בדקת שהחיישן והמשאבה מחוברים חזק לעור?"],
    ["🍎", "האם אכלת ארוחות מדוייקות היום?"],
    ["🩸", "האם עשית בדיקה באצבע או כיול לאחרונה?"],
  ];

  let transcript = "";
  let answers = new Array(QUESTIONS.length).fill(null);

  const errorBox = document.getElementById("error-box");
  const screens = {
    intro: document.getElementById("screen-intro"),
    questions: document.getElementById("screen-questions"),
  };

  function showScreen(name) {
    Object.values(screens).forEach((el) => el.classList.remove("active"));
    screens[name].classList.add("active");
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.style.display = "block";
  }

  function clearError() {
    errorBox.style.display = "none";
    errorBox.textContent = "";
  }

  // The SUGARBUDDY_CONTEXT marker carries conversation state and MUST stay in
  // `transcript` (it is what the next /api/execute call round-trips), but it is
  // base64 gibberish to a human, so hide it from any on-screen response text.
  function stripMarker(text) {
    return text.replace(/<!--\s*SUGARBUDDY_CONTEXT:[\s\S]*?-->/g, "").trimEnd();
  }

  function renderStepBlock(step) {
    const details = document.createElement("details");
    details.className = "step-block";
    const summary = document.createElement("summary");
    summary.textContent = step.module;
    details.appendChild(summary);
    const pre = document.createElement("pre");
    pre.textContent =
      "SYSTEM PROMPT:\n" + step.prompt.system_prompt +
      "\n\nUSER PROMPT:\n" + step.prompt.user_prompt +
      "\n\nRESPONSE:\n" + JSON.stringify(step.response, null, 2);
    details.appendChild(pre);
    return details;
  }

  function renderTechTrace(container, steps) {
    container.innerHTML = "";
    if (!steps || steps.length === 0) return;
    const details = document.createElement("details");
    details.className = "tech-trace";
    const summary = document.createElement("summary");
    summary.textContent = "פרטים טכניים";
    details.appendChild(summary);
    steps.forEach((step) => details.appendChild(renderStepBlock(step)));
    container.appendChild(details);
  }

  async function callExecute(promptText) {
    const res = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: promptText }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  // --- Intro screen ---
  const introInput = document.getElementById("intro-input");
  const introButton = document.getElementById("intro-button");

  introButton.addEventListener("click", async () => {
    clearError();
    const text = introInput.value.trim();
    if (!text) return;
    introButton.disabled = true;
    try {
      const data = await callExecute(text);
      if (data.status === "error") {
        showError("שגיאה: " + data.error);
        return;
      }
      transcript = text + "\n" + data.response;
      renderQuestions();
      renderTechTrace(document.getElementById("questions-tech-trace"), data.steps);
      showScreen("questions");
    } catch (err) {
      showError("הבקשה נכשלה: " + err);
    } finally {
      introButton.disabled = false;
    }
  });

  // --- Questions screen ---
  const questionsList = document.getElementById("questions-list");
  const progressCount = document.getElementById("progress-count");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const questionsContinueButton = document.getElementById("questions-continue-button");

  function renderQuestions() {
    answers = new Array(QUESTIONS.length).fill(null);
    questionsList.innerHTML = "";
    QUESTIONS.forEach(([emoji, text], index) => {
      const card = document.createElement("div");
      card.className = "card question-card";

      const header = document.createElement("div");
      header.className = "question-header";
      const badge = document.createElement("span");
      badge.className = "question-badge";
      badge.textContent = String(index + 1);
      const emojiSpan = document.createElement("span");
      emojiSpan.textContent = emoji;
      const textSpan = document.createElement("span");
      textSpan.textContent = text;
      textSpan.style.flex = "1";
      header.append(textSpan, emojiSpan, badge);
      card.appendChild(header);

      const buttons = document.createElement("div");
      buttons.className = "question-buttons";
      const noBtn = document.createElement("button");
      noBtn.className = "yn-btn";
      noBtn.textContent = "לא";
      const yesBtn = document.createElement("button");
      yesBtn.className = "yn-btn";
      yesBtn.textContent = "כן";

      function select(value, chosenBtn, otherBtn) {
        answers[index] = value;
        chosenBtn.classList.add("selected");
        otherBtn.classList.remove("selected");
        updateProgress();
      }
      noBtn.addEventListener("click", () => select(false, noBtn, yesBtn));
      yesBtn.addEventListener("click", () => select(true, yesBtn, noBtn));

      // Under dir="rtl", the first-appended flex child renders on the right —
      // append yesBtn first so "כן" lands on the right and "לא" on the left,
      // matching the provided mockup.
      buttons.append(yesBtn, noBtn);
      card.appendChild(buttons);
      questionsList.appendChild(card);
    });
    updateProgress();
  }

  function updateProgress() {
    const answeredCount = answers.filter((a) => a !== null).length;
    progressCount.textContent = String(answeredCount);
    progressBarFill.style.width = (answeredCount / QUESTIONS.length) * 100 + "%";
    questionsContinueButton.disabled = answeredCount < QUESTIONS.length;
  }

  questionsContinueButton.addEventListener("click", async () => {
    clearError();
    const lines = answers.map((value, index) => `${index + 1}. ${value ? "כן" : "לא"}`);
    const answerText = lines.join(" ");
    questionsContinueButton.disabled = true;
    try {
      const data = await callExecute(transcript + "\n" + answerText);
      if (data.status === "error") {
        showError("שגיאה: " + data.error);
        questionsContinueButton.disabled = false;
        return;
      }
      transcript = transcript + "\n" + answerText + "\n" + data.response;
      console.log("Turn 2 response (Task 2 will branch on this):", data.response);
    } catch (err) {
      showError("הבקשה נכשלה: " + err);
      questionsContinueButton.disabled = false;
    }
  });
</script>
</body>
</html>
```

Before moving on, diff the 10 question strings in the `QUESTIONS` array above against
`questionnaire.py:8-17` character-for-character (the display text isn't used for parsing, but it
must match the canonical wording exactly — a transcription slip here was already caught and fixed
once while drafting this plan).

Note: the `questionsContinueButton` click handler above is intentionally incomplete (it only
logs the response) — Task 2 replaces that `console.log` line with the real branch to the
Follow-up/Summary screens, since those screens don't exist yet.

- [ ] **Step 2: Manual verification**

Start the server: `uvicorn api.index:app --reload`. Open `http://127.0.0.1:8000/` in a browser.

Verify visually: gradient background with two soft blurred circles, no console errors, Intro
screen shows title + subtitle + textarea + "התחל" button in the maroon theme.

In the DevTools console, paste the fetch-mock snippet from "Manual verification technique" above,
then run:

```js
window.__mockResponse = {
  status: "ok", error: null,
  response: "Thanks — before I can investigate, please answer these yes/no questions.\n\n<!-- SUGARBUDDY_CONTEXT: eyJzdGFnZSI6ICJxdWVzdGlvbm5haXJlX3NlbnQifQ== -->",
  steps: [{ module: "CGM Event", prompt: { system_prompt: "test sp", user_prompt: "test up" }, response: { type: "glucose_extreme" } }],
};
```

Type any text into the Intro textarea and click "התחל". Verify: the Questions screen appears
with all 10 question cards (correct emoji/text/numbering per `questionnaire.py`), progress reads
"0 מתוך 10", the "המשך" button is disabled. Click a few Yes/No buttons and verify: the clicked
button highlights (solid maroon fill), the progress count/bar update, and clicking the other
button on an already-answered question moves the highlight without double-counting. After
answering all 10, verify the "המשך" button becomes enabled. Expand "פרטים טכניים" below the
question list and verify it shows the "CGM Event" step with the mocked prompt/response.

Compare the rendered Questions screen against the user's first mockup screenshot and adjust
spacing/gap CSS if it looks visibly off.

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "Redesign GUI: theme shell, Intro screen, Questions screen with Yes/No buttons"
```

---

### Task 2: Follow-up screen and Summary screen

**Files:**
- Modify: `static/index.html`

**Interfaces:**
- Consumes: `showScreen`, `stripMarker`, `renderTechTrace`, `callExecute`, `transcript`,
  `screens` object — all from Task 1.
- Produces: adds `"followup"` and `"summary"` keys to the `screens` object; the
  `questionsContinueButton` click handler now branches to one of these two screens instead of
  only logging.

- [ ] **Step 1: Add the two new `<section>` elements**

In `static/index.html`, immediately after the `</section>` that closes `#screen-questions` (and
before the closing `</div>` of `<div class="app">`), insert:

```html
  <section id="screen-followup" class="screen">
    <h1 class="screen-title">עוד שאלה קצרה</h1>
    <p class="screen-subtitle">התשובה שלך תעזור לנו להבין טוב יותר מה קרה.</p>
    <div class="card followup-card">
      <p class="followup-label">שאלת המשך</p>
      <p id="followup-question-text" class="followup-question-text"></p>
    </div>
    <label for="followup-input" style="font-weight:600;">התשובה שלי <span class="required-mark">*</span></label>
    <textarea id="followup-input" maxlength="500" placeholder="אפשר לכתוב כאן תשובה קצרה..."></textarea>
    <div id="followup-char-counter" class="char-counter">0/500</div>
    <button id="followup-send-button" class="btn-primary">שלח</button>
    <div id="followup-tech-trace"></div>
  </section>

  <section id="screen-summary" class="screen">
    <h1 class="screen-title">הסיכום שלנו</h1>
    <div class="card">
      <p id="summary-response-text" style="white-space: pre-wrap; margin: 0;"></p>
    </div>
    <label for="parent-decision-input" style="font-weight:600;">החלטת ההורה</label>
    <textarea id="parent-decision-input" placeholder="מה הנער/ה צריכ/ה לעשות?"></textarea>
    <button id="send-to-teen-button" class="btn-primary">שלח לנער/ה</button>
    <div id="summary-tech-trace"></div>
  </section>
```

- [ ] **Step 2: Add the matching CSS**

In the `<style>` block, immediately before the closing `</style>` tag, insert:

```css
  .followup-card { border: 2px solid var(--color-primary); }
  .followup-label { font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 0.25rem; }
  .followup-question-text { font-weight: 700; font-size: 1.1rem; margin: 0; }
  .required-mark { color: var(--color-primary); }
  .char-counter { text-align: left; font-size: 0.8rem; color: var(--color-text-muted); margin-top: 0.25rem; }
```

- [ ] **Step 3: Register the two screens and wire their behavior**

In the `<script>` block, change the `screens` object (from Task 1) to:

```js
  const screens = {
    intro: document.getElementById("screen-intro"),
    questions: document.getElementById("screen-questions"),
    followup: document.getElementById("screen-followup"),
    summary: document.getElementById("screen-summary"),
  };
```

Replace the `questionsContinueButton` click handler's body (the one Task 1 left with a
`console.log` placeholder) with:

```js
  questionsContinueButton.addEventListener("click", async () => {
    clearError();
    const lines = answers.map((value, index) => `${index + 1}. ${value ? "כן" : "לא"}`);
    const answerText = lines.join(" ");
    questionsContinueButton.disabled = true;
    try {
      const data = await callExecute(transcript + "\n" + answerText);
      if (data.status === "error") {
        showError("שגיאה: " + data.error);
        questionsContinueButton.disabled = false;
        return;
      }
      transcript = transcript + "\n" + answerText + "\n" + data.response;
      if (data.response.includes("SUGARBUDDY_CONTEXT")) {
        document.getElementById("followup-question-text").textContent = stripMarker(data.response);
        document.getElementById("followup-input").value = "";
        document.getElementById("followup-char-counter").textContent = "0/500";
        renderTechTrace(document.getElementById("followup-tech-trace"), data.steps);
        showScreen("followup");
      } else {
        document.getElementById("summary-response-text").textContent = stripMarker(data.response);
        renderTechTrace(document.getElementById("summary-tech-trace"), data.steps);
        showScreen("summary");
      }
    } catch (err) {
      showError("הבקשה נכשלה: " + err);
      questionsContinueButton.disabled = false;
    }
  });
```

Immediately after that handler (still inside `<script>`, before the closing `</script>` tag),
add the Follow-up and Summary screens' own logic:

```js
  // --- Follow-up screen ---
  const followupInput = document.getElementById("followup-input");
  const followupCharCounter = document.getElementById("followup-char-counter");
  const followupSendButton = document.getElementById("followup-send-button");

  followupInput.addEventListener("input", () => {
    followupCharCounter.textContent = followupInput.value.length + "/500";
  });

  followupSendButton.addEventListener("click", async () => {
    clearError();
    const text = followupInput.value.trim();
    if (!text) return;
    followupSendButton.disabled = true;
    try {
      const data = await callExecute(transcript + "\n" + text);
      if (data.status === "error") {
        showError("שגיאה: " + data.error);
        return;
      }
      transcript = transcript + "\n" + text + "\n" + data.response;
      document.getElementById("summary-response-text").textContent = stripMarker(data.response);
      renderTechTrace(document.getElementById("summary-tech-trace"), data.steps);
      showScreen("summary");
    } catch (err) {
      showError("הבקשה נכשלה: " + err);
    } finally {
      followupSendButton.disabled = false;
    }
  });
```

- [ ] **Step 4: Manual verification — both branches**

Start `uvicorn api.index:app --reload`, open `http://127.0.0.1:8000/`, paste the fetch-mock
snippet from the top of this plan.

**Branch A — follow-up needed.** Set:

```js
window.__mockResponse = {
  status: "ok", error: null,
  response: "Thanks...\n\n<!-- SUGARBUDDY_CONTEXT: eyJzdGFnZSI6ICJxdWVzdGlvbm5haXJlX3NlbnQifQ== -->",
  steps: [{ module: "CGM Event", prompt: { system_prompt: "sp", user_prompt: "up" }, response: {} }],
};
```

Click "התחל", answer all 10 questions, then set:

```js
window.__mockResponse = {
  status: "ok", error: null,
  response: "האם אכלת את ארוחת העשר שלך?\n\n<!-- SUGARBUDDY_CONTEXT: eyJzdGFnZSI6ICJmb2xsb3d1cF9zZW50In0= -->",
  steps: [{ module: "ReAct Agent", prompt: { system_prompt: "sp", user_prompt: "up" }, response: { need_more_info: true } }],
};
```

Click "המשך". Verify: the Follow-up screen appears, showing the question text (marker stripped),
"0/500" counter. Type text and verify the counter updates live. Then set:

```js
window.__mockResponse = {
  status: "ok", error: null,
  response: "האירוע היה עלייה חדה בגלוקוז... (final parent summary, no marker)",
  steps: [{ module: "Confidence Classification", prompt: { system_prompt: "sp", user_prompt: "up" }, response: {} }],
};
```

Click "שלח". Verify: the Summary screen appears with the response text shown, and expanding
"פרטים טכניים" shows the "Confidence Classification" step.

**Branch B — no follow-up.** Reload the page, repeat with the Intro→Questions mocks above, but
on the post-questions mock use a `response` with NO `SUGARBUDDY_CONTEXT` substring (e.g. just
`"final parent summary text"`). Verify: after clicking "המשך", the Summary screen appears
directly (Follow-up screen is skipped).

Compare both screens against the user's second mockup screenshot (follow-up) and adjust CSS if
visibly off.

- [ ] **Step 5: Commit**

```bash
git add static/index.html
git commit -m "Add Follow-up and Summary screens, wire the questions-to-next-screen branch"
```

---

### Task 3: Teen-message screen, reset flow, full walkthrough (incl. error path)

**Files:**
- Modify: `static/index.html`

**Interfaces:**
- Consumes: `showScreen`, `screens`, `transcript`, `answers`, `introInput`, all from Tasks 1-2.
- Produces: adds `"teen"` to the `screens` object; a full reset path back to `"intro"`.

- [ ] **Step 1: Add the Teen-message `<section>`**

Immediately after the `</section>` that closes `#screen-summary`, insert:

```html
  <section id="screen-teen" class="screen">
    <h1 class="screen-title">המלצת ההורה היא:</h1>
    <div class="card teen-message-card">
      <p id="teen-message-text" style="white-space: pre-wrap; margin:0;"></p>
    </div>
    <div class="card">
      <p style="font-weight:700; margin-top:0;">ביצעת את ההמלצה?</p>
      <div class="confirm-options">
        <div class="confirm-option" data-value="did">עשיתי</div>
        <div class="confirm-option" data-value="didnt">לא עשיתי</div>
      </div>
      <button id="finish-button" class="btn-primary">המשך לסיום האירוע</button>
    </div>
  </section>
```

- [ ] **Step 2: Add the matching CSS**

Before the closing `</style>` tag, insert:

```css
  .teen-message-card { border: 2px solid var(--color-primary); font-size: 1.05rem; }
  .confirm-options { display: flex; flex-direction: column; gap: 0.75rem; margin: 1rem 0; }
  .confirm-option {
    display: flex; align-items: center; gap: 0.5rem;
    border: 1px solid var(--color-border); border-radius: 10px; padding: 0.9rem 1.25rem;
    cursor: pointer; font-weight: 600;
  }
  .confirm-option.selected { border-color: var(--color-primary); background: var(--color-card-alt); }
```

- [ ] **Step 3: Register the screen and wire Summary → Teen → reset**

Update the `screens` object (from Task 2) to its final, complete form:

```js
  const screens = {
    intro: document.getElementById("screen-intro"),
    questions: document.getElementById("screen-questions"),
    followup: document.getElementById("screen-followup"),
    summary: document.getElementById("screen-summary"),
    teen: document.getElementById("screen-teen"),
  };
```

Add the Teen screen's wiring — Task 2 left `#send-to-teen-button` in the HTML but did not attach
a listener — by adding, after the Follow-up/Summary script block from Task 2:

```js
  // --- Summary screen: send to teen ---
  const parentDecisionInput = document.getElementById("parent-decision-input");
  const sendToTeenButton = document.getElementById("send-to-teen-button");

  sendToTeenButton.addEventListener("click", () => {
    const text = parentDecisionInput.value.trim();
    if (!text) return;
    document.getElementById("teen-message-text").textContent = text;
    document.querySelectorAll(".confirm-option").forEach((el) => el.classList.remove("selected"));
    showScreen("teen");
  });

  // --- Teen screen ---
  document.querySelectorAll(".confirm-option").forEach((el) => {
    el.addEventListener("click", () => {
      document.querySelectorAll(".confirm-option").forEach((o) => o.classList.remove("selected"));
      el.classList.add("selected");
    });
  });

  document.getElementById("finish-button").addEventListener("click", () => {
    transcript = "";
    answers = new Array(QUESTIONS.length).fill(null);
    introInput.value = "";
    parentDecisionInput.value = "";
    clearError();
    showScreen("intro");
  });
```

- [ ] **Step 4: Full manual walkthrough**

Start `uvicorn api.index:app --reload`, open `http://127.0.0.1:8000/`, paste the fetch-mock
snippet.

Walk the entire flow start to finish using the Branch A mocks from Task 2 (with a follow-up),
through to the Summary screen. On the Summary screen, type parent-decision text and click "שלח
לנער/ה". Verify: the Teen screen appears showing that exact text in the bordered card. Click
"עשיתי" and verify it highlights (and clicking "לא עשיתי" moves the highlight, only one selected
at a time). Click "המשך לסיום האירוע" and verify: the app returns to the Intro screen, the Intro
textarea is empty, and repeating the whole flow from scratch works cleanly (no stale answers or
leftover text from the previous run).

Repeat the full walkthrough once more using Branch B (no follow-up) end to end.

Then verify the error path: set `window.__mockResponse` unused and instead override fetch to
throw, e.g. paste `window.fetch = async () => { throw new Error("network down"); };`, click
"התחל", and verify the error box appears in the theme's colors with a readable message, and the
Intro screen does not advance.

Compare the Teen screen against the user's third mockup screenshot and adjust CSS if visibly off.

- [ ] **Step 5: Commit**

```bash
git add static/index.html
git commit -m "Add Teen-message screen, full reset flow, and error-box theming"
```
