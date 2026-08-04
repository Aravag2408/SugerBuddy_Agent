# Agent Reasoning Pipeline — Design

## Context

The course assignment (`Project.pdf`) grades the agent through one contract: `POST /api/execute`
takes `{"prompt": "<string>"}` and returns `{"status", "error", "response", "steps"}`, where
`steps` logs every LLM call with a `module` name that must stay consistent with the required
architecture diagram. There is no push/live-feed mechanism in that contract — the grader can only
ever call `/api/execute` with whatever text they type.

SugarBuddy's intended pipeline (team diagram):

```
CGM Event -> Structured Questionnaire (10 yes/no) -> ReAct Agent -> Confidence Classification -> Parent Summary
```

`sugarbuddy_anomaly_detector.py` (live Nightscout polling, anomaly detection, case tracking) and
`local_prototype.py` (CGM event -> questionnaire -> keyword-matched context retrieval -> **stubbed**
agent call) are already built. Neither calls a real LLM yet, and neither the Confidence
Classification stage nor Pinecone-based retrieval exist yet.

## Decisions made during brainstorming

- **Live CGM feed is decoupled from grading.** `sugarbuddy_anomaly_detector.py` stays as-is (real,
  working integration), but the graded pipeline treats "CGM Event" as something described in the
  prompt (structured JSON or plain language), not something it must fetch live. This is what lets
  a grader invent arbitrary test scenarios and get repeatable results, and it sidesteps the fact
  that Vercel serverless has no persistent process to poll with anyway.
- **Multi-turn, not single-shot.** The questionnaire is answered in a follow-up call, matching the
  diagram and the course's optional "back-and-forth interaction" / "conversation history" features.
  Since the API contract is a single string, multi-turn is implemented by having the client resend
  the **entire transcript** as the new `prompt` each call — no server-side session store needed.
- **The ReAct Agent can ask at most one follow-up question of its own wording.** After reasoning
  over the anomaly + 10 answers + retrieved context, it may decide it needs one more piece of
  information from the teen. If so, it writes that question itself (not picked from a fixed list —
  genuine ReAct Reason -> Act -> Observe, bounded to a single extra round so cost/latency stay
  predictable). If it already has enough, it skips straight to final findings.
- **Pinecone + `text-embedding-3-small`** replaces the current keyword-substring matching in
  `retrieve_context()`, to actually use the vector-DB stack the course provides.
- **Supabase usage is minimal**: a non-blocking audit log of each `/api/execute` call (prompt,
  response, steps, timestamp). Nothing in the pipeline reads from Supabase mid-request, so an
  outage there can't break the agent. The earlier `anomaly-scheduler` spec (GitHub Actions cron +
  Supabase case tracking) is deferred — useful for a real product, not required for grading.
- **Parent Summary is parent-only**, and must read as: a short recap of the event, followed by up
  to three possible reasons (ordered by confidence), followed by one practical suggestion. No
  separate `teen_guidance` field (dropped from the earlier stub's shape).
- **Confidence Classification stays a separate LLM call**, matching the diagram literally — with a
  mini model and small per-call context, the extra call costs a rounding error against the $13
  budget; dev-time iteration will consume far more of it than graded runs will.
- **Questionnaire is finalized at 10 questions** (the 9 already in code, plus a 10th: recent
  finger-stick check or sensor calibration — relevant because it can explain a reading discrepancy
  rather than a genuine glucose event).
- **The parent's decision, once written, is relayed to the teen as plain pass-through text** — no
  LLM rephrasing, no new module. This is a GUI-level feature (a parent-facing box and a teen-facing
  display), not part of the reasoning pipeline, and is explicitly out of scope for this spec.

## Scope

This spec covers the **core reasoning pipeline only**: parsing a CGM event out of a prompt,
running the questionnaire exchange (which may span two or three conversational turns depending on
whether the ReAct Agent asks its one optional follow-up), Pinecone-backed retrieval, and the three
LLM reasoning stages.

**Explicitly out of scope** (separate follow-on specs): the FastAPI app and its four required
endpoints, the `/api/model_architecture` PNG export (the team's existing pipeline diagram image is
a strong candidate to adapt for this), the GUI, Vercel deployment, and the parent-decision-to-teen
relay (plain text pass-through at the GUI layer, no agent involvement).

## Questionnaire (final, 10 questions)

| key | text |
|---|---|
| `ate_recently` | אכלת משהו בתוך השעתיים האחרונות? |
| `carb_count_accurate` | האם הזנת כמות מדוייקת של פחמימות או בערך? |
| `exercised_last_4h` | רצת, קפצת, או עשית שיעור ספורט ואימון ב-4 השעות האחרונות? |
| `stressed_last_30min` | מישהו הרגיז אותך או שהיית בלחץ גדול בחצי השעה האחרונה? |
| `drank_water_today` | שתית לפחות 4 כוסות מים במהלך היום? |
| `hot_weather_last_30min` | האם היית בחוץ במזג אוויר חם מאוד בחצי השעה האחרונה? |
| `correction_dose_last_3h` | החלפת משאבה או לקחת מנת תיקון (או פחמימות מהירות להיפו) ב-3 השעות האחרונות? |
| `phone_sensor_check_last_hour` | האם היית צמודה לטלפון הנייד בשעה האחרונה, והאם בדקת שהחיישן והמשאבה מחוברים חזק לעור? |
| `accurate_meals_today` | האם אכלת ארוחות מדוייקות היום? |
| `finger_stick_or_calibration_recent` | האם עשית בדיקה באצבע או כיול לאחרונה? |

## Modules

Names below are used verbatim in `steps`, the architecture diagram, and any descriptions.

| Module | LLM call? | Job |
|---|---|---|
| `CGM Event` | Only if the prompt is free text; skipped if it's parseable JSON | Normalize the prompt into `{type, severity, direction, message, details}` |
| `Structured Questionnaire` | No — deterministic | Emit the fixed 10-question list |
| `ReAct Agent` | Yes, 1–2 calls | Reason over anomaly + answers + Pinecone-retrieved context; may ask **one** self-worded follow-up question before finalizing candidate findings with cited evidence |
| `Confidence Classification` | Yes, 1 call | Score each finding's confidence |
| `Parent Summary` | Yes, 1 call | Event recap + up to 3 possible reasons + one suggestion, for the parent |

Worst case per full round trip (all three turns, follow-up asked): 5 LLM calls + 2 embedding calls
(retrieval reruns in turn 3). Common case (no follow-up needed): 4 LLM calls + 1 embedding call.

## Conversation state machine

Since `/api/execute` takes a single string and there's no server-side session store, the client
resends the whole transcript each call, and the server tracks where it is in the flow via an inert
marker embedded in its own previous response:

```
<!-- SUGARBUDDY_CONTEXT: {"stage": "...", ...} -->
```

| Stage found in incoming prompt | Meaning | What happens next |
|---|---|---|
| *(none)* | Fresh CGM event | Turn 1 flow |
| `questionnaire_sent` | Teen just answered the 10 questions | Turn 2 flow |
| `followup_sent` | Teen just answered the ReAct Agent's one follow-up question | Turn 3 flow |

### Turn 1 — CGM event in, questionnaire out

1. `parse_cgm_event(prompt) -> Anomaly`:
   - Attempt `json.loads` on the prompt (or on a regex-extracted `{...}` block within it). If the
     result has recognizable fields (`type`/`sgv`/`glucose`/etc.), map directly to
     `Anomaly{type, severity, direction, message, details}` — **no LLM call**.
   - Otherwise, one `CGM Event` LLM call:
     - *System prompt*: "Extract a CGM (continuous glucose monitor) event from the user's
       description. Return ONLY JSON: {type, severity, direction, message, details}. type must be
       one of [rate_of_change, big_gap, iob_contextual, glucose_extreme]. severity must be one of
       [warning, urgent]. direction must be 'high', 'low', or null. If the description does not
       describe a glucose event, return {"error": "not a CGM event description"}."
     - *User prompt*: the raw incoming prompt text.
   - If parsing yields `{"error": ...}` or fails outright, raise `PipelineError("not a recognizable
     CGM event description")`.
2. `format_questionnaire_prompt(anomaly) -> str` builds the turn-1 response: the 10 questions
   (instructing the reply be a numbered Y/N list, e.g. `"1. Y 2. N ..."`, plus an optional notes
   line), followed by the marker `<!-- SUGARBUDDY_CONTEXT: {"stage": "questionnaire_sent", "anomaly": {...}} -->`.
3. Return `{response: <that text>, steps: [<CGM Event step, if an LLM call happened>]}`.

### Turn 2 — 10 answers in, either a follow-up question or the final summary out

1. `extract_conversation_state(prompt) -> ConversationState | None`:
   - Find the marker. If its `stage` is `questionnaire_sent`, parse answers from the text following
     the marker with a regex matching `\d+\.\s*(Y|N|Yes|No|כן|לא)` (case-insensitive), mapping
     question-number -> boolean in questionnaire order. Anything left over after the numbered
     answers becomes free-text `notes`.
   - If fewer than 10 answers are recognized, raise `PipelineError("could not parse all
     questionnaire answers; reply as a numbered Y/N list")`.
2. `retrieve_context_pinecone(anomaly, answers) -> dict`:
   - If `anomaly.details.get("direction")` is `None` (e.g. a `big_gap` anomaly carries no
     glucose-direction information), return `{table_matches: [], rag_snippet: ""}` immediately —
     same short-circuit `retrieve_context()` already does; no embedding or Pinecone call needed.
   - Otherwise, build a short query string: anomaly message + direction + the Hebrew text of every
     "yes"-answered question.
   - One embedding call (`text-embedding-3-small`) on that query string.
   - Query the `causes` Pinecone namespace (top 3), filtered by metadata `state` matching the
     anomaly's direction (`high` -> `"היפר"`, `low` -> `"היפו"`).
   - Query the `reference` Pinecone namespace (top 2), filtered by metadata `direction` matching
     the anomaly's direction.
   - Return `{table_matches: [...], rag_snippet: "..."}` — same shape `retrieve_context()` already
     produces, so downstream prompt-building code is unaffected by the retrieval-method swap.
   - **Fallback:** if the embedding call or Pinecone query fails, fall back to the existing
     keyword-matching `retrieve_context()` rather than failing the request.
3. `run_react_agent(anomaly, answers, notes, context, followup=None, allow_followup=True) -> tuple[dict, step]`:
   - *System prompt*: "You are a diabetes event investigation assistant for a parent-teen pair.
     Given a CGM anomaly, structured yes/no answers with free-text notes, retrieved candidate-cause
     table rows, and medical reference text, reason step by step. If one additional piece of
     information from the teen would meaningfully change your findings, return ONLY JSON:
     {need_more_info: true, followup_question: "<your question, in Hebrew>", findings: null}.
     Otherwise return ONLY JSON: {need_more_info: false, followup_question: null, findings: [{cause,
     evidence, source}]}, source being one of 'table', 'reference', 'answers'. List up to 3
     findings ordered by plausibility. Do not diagnose or invent facts not supported by the given
     context." When `allow_followup=False` (turn 3, see below), append: "You must set
     need_more_info to false and provide findings now — no further follow-up is allowed."
   - *User prompt*: anomaly + answers + notes + `context.table_matches` + `context.rag_snippet` (+
     the follow-up Q&A if this is the turn-3 call), serialized compactly.
   - If `need_more_info` is true: return `{response: <followup_question text>, steps: [...,
     ReAct Agent step]}`, with the response marker
     `<!-- SUGARBUDDY_CONTEXT: {"stage": "followup_sent", "anomaly": {...}, "answers": {...},
     "notes": "...", "followup_question": "..."} -->`. This ends the turn.
   - If `need_more_info` is false: continue to Confidence Classification and Parent Summary within
     this same turn (steps 4–5 below), passing `findings`.
   - **Safety net:** if this was the forced-final call (`allow_followup=False`) and the model still
     returns `need_more_info: true`, ignore that flag and proceed with whatever `findings` were
     returned (empty list if none) — the pipeline must never loop a second time.

### Turn 3 (conditional) — follow-up answer in, final summary out

Only entered when the incoming prompt's marker has `stage == "followup_sent"`.

1. Parse the teen's reply to the single follow-up question as free text (no strict format needed —
   it's one open question, not a list).
2. Re-run `retrieve_context_pinecone(anomaly, answers)` (cheap, idempotent — simpler than
   serializing the previous context through the marker).
3. Call `run_react_agent(..., followup={"question": ..., "answer": ...}, allow_followup=False)` —
   this call must finalize (see safety net above).
4. Continue to Confidence Classification and Parent Summary (steps 4–5 below).

### Finalization (shared by turn 2's no-follow-up path and turn 3)

4. `run_confidence_classification(anomaly, answers, findings) -> tuple[dict, step]`:
   - *System prompt*: "You score confidence for each candidate finding about what caused a glucose
     anomaly. Given the anomaly, questionnaire answers, and a list of candidate findings with their
     supporting evidence, return ONLY JSON: {findings: [{cause, evidence, confidence, rationale}]},
     preserving each finding's cause/evidence and adding confidence ('low'|'medium'|'high') and a
     one-sentence rationale. Base confidence on how directly the evidence supports each cause."
   - *User prompt*: anomaly + answers + the `findings` list from `run_react_agent` (not the raw
     retrieved context again — keeps this call's prompt small).
   - Output: `{findings: [...with confidence + rationale added...]}`.
5. `run_parent_summary(anomaly, answers, findings) -> tuple[dict, step]`:
   - *System prompt*: "You write a parent-facing summary of a glucose anomaly investigation. Given
     the anomaly, the teen's questionnaire answers, and confidence-scored candidate findings,
     return ONLY JSON: {parent_summary}. parent_summary must read as: a 2-3 sentence recap of the
     event and what the teen reported, then up to three possible reasons ordered by confidence
     (each stated with its confidence level), then one practical suggestion. Do not diagnose;
     present reasons as possibilities, not conclusions."
   - *User prompt*: anomaly (brief) + answers + the confidence-scored findings.
   - Output: `{parent_summary: "..."}` — this text is the final `response` returned to the caller.
6. Return `{response: parent_summary, steps: [...ReAct Agent step(s), Confidence Classification step, Parent Summary step]}`.

## Pinecone ingestion (one-time script)

- Embed each row of `investigation_table.json` (concatenated `category` + `cause` + `explanation`)
  into the `causes` namespace, metadata `{state, category, cause, explanation, time_to_effect}`.
- Chunk `data/rag/ada_diabetes_association.txt` by its existing `## HYPERGLYCEMIA` / `##
  HYPOGLYCEMIA` section markers and `data/rag/niddk_hypoglycemia.txt` as a single hypoglycemia
  chunk; embed each into the `reference` namespace, metadata `{direction: "high"|"low", source_file}`.
- Re-run only when the source table or RAG text changes; not part of the request-time path.
- Source data currently checked in: `data/investigation_table.json` (~87 rows) and the two files
  under `data/rag/`. No other source material (the original pptx/docx/xlsx) is in the repo — only
  these already-parsed derivatives, which is what ingestion reads.

## Function-level interface (for later FastAPI wiring)

```
parse_cgm_event(prompt, llm_client) -> Anomaly
format_questionnaire_prompt(anomaly) -> str
extract_conversation_state(prompt) -> ConversationState | None
retrieve_context_pinecone(anomaly, answers, embed_client, pinecone_index) -> dict
run_react_agent(anomaly, answers, notes, context, llm_client, followup=None, allow_followup=True) -> tuple[dict, step]
run_confidence_classification(anomaly, answers, findings, llm_client) -> tuple[dict, step]
run_parent_summary(anomaly, answers, findings, llm_client) -> tuple[dict, step]
run_pipeline(prompt, clients) -> {"response": str, "steps": list[dict]}
```

`run_pipeline` is the single entry point the (future) `/api/execute` handler calls; it dispatches
on `extract_conversation_state`'s stage (none / `questionnaire_sent` / `followup_sent`) and returns
exactly the `response`/`steps` shape the course requires (the FastAPI layer wraps this in
`{status, error, ...}`).

## Error handling

- **Unparseable CGM event** (turn 1): `PipelineError("not a recognizable CGM event description")`.
- **Unparseable answers** (turn 2): `PipelineError("could not parse all questionnaire answers; reply as a numbered Y/N list")`.
- **Pinecone/embedding failure**: caught, falls back to the existing keyword-matching
  `retrieve_context()` — the request still completes.
- **LLM call failure** (`ReAct Agent` / `Confidence Classification` / `Parent Summary`): no
  fallback possible for core reasoning; raise `PipelineError` with the underlying message. The
  FastAPI layer (separate spec) maps any `PipelineError` to `{"status": "error", "error": str(e)}`.
- **ReAct Agent disobeys the forced-final instruction** (turn 3 still returns `need_more_info:
  true`): ignored by the pipeline, which proceeds with whatever `findings` were returned — the
  follow-up loop never runs more than once regardless of what the model asks for.

## Testing

- Unit tests per function with fake LLM/embedding/Pinecone clients (dependency-injected):
  - `parse_cgm_event`: JSON-shortcut path and free-text LLM-fallback path, including the
    `{"error": ...}` rejection case.
  - `extract_conversation_state`: no marker (fresh turn 1), `questionnaire_sent` stage with Hebrew
    (`כן`/`לא`) and English (`Y`/`N`) answer replies, notes-tail extraction, the
    fewer-than-10-answers error, and `followup_sent` stage parsing.
  - `retrieve_context_pinecone`: mocked Pinecone index, asserts correct namespace/metadata filters
    and the fallback path when the mock raises.
  - `run_react_agent`: both branches (`need_more_info: true` ends the turn with a question;
    `need_more_info: false` proceeds to finalization) and the forced-final safety net when
    `allow_followup=False` and the mock still returns `need_more_info: true`.
  - `run_confidence_classification` / `run_parent_summary`: assert prompt shape and that each
    stage's output threads into the next, using canned mock LLM responses (not live calls).
- One manual end-to-end smoke test extending `local_prototype.py`'s pattern: run the full flow
  (including a scenario that triggers the follow-up question, and one that doesn't) against real
  LLMod.ai + Pinecone with fabricated scenarios, confirm the final `parent_summary` contains an
  event recap + up to 3 reasons + a suggestion, and that `steps` are well-formed and consistently
  named.
