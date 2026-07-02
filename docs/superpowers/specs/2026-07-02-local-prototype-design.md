# Local Prototype — Design

## Context

The full SugarBuddy pipeline (per `Parent-Teen-Diabetes-Investigation-Agent.pptx`) is:

```
CGM Event -> Structured Questionnaire (9 yes/no + notes) -> ReAct Agent -> Parent Summary + Teen Guidance
```

The course assignment (`Project.pdf`) requires the final system to be a FastAPI service on
Vercel exposing `GET /api/team_info`, `GET /api/agent_info`, `GET /api/model_architecture`,
and `POST /api/execute` (prompt in, `{response, steps}` out, where `steps` logs every LLM
call with `module`, `system_prompt`/`user_prompt`, and `response`). The LLM provider is
LLMod.ai (`gpt-5.4-mini` for text, `text-embedding-3-small` for embeddings), with a **total
team budget of $13**. RAG is expected to use Pinecone as the vector store; Supabase is the
primary DB.

Building straight toward that full contract before the core agent logic has ever been
exercised end-to-end is risky — it mixes infrastructure debugging with reasoning-logic
debugging. This spec covers a **local, zero-cost prototype** that exercises the full
CGM-event → questionnaire → (stubbed) agent flow on a laptop, with no cloud services, no
LLM calls, and no deployment. It produces output already shaped like the course's required
`steps` schema, so wiring in the real LLM call later is a small, isolated change rather than
a rework.

**Out of scope for this spec:** the real LLM call, Pinecone/embeddings, Supabase, the FastAPI
app and its required endpoints, the GUI, and deployment. Those come after this prototype
proves the reasoning-input shape is right.

## Data sources (real, not fabricated)

- **RAG text** — `data/rag/ada_diabetes_association.txt`: real extracted text from the
  team's own "American Diabetes Association.docx", covering hyperglycemia (causes,
  symptoms, treatment, ketoacidosis) and hypoglycemia (causes, symptoms, the 15-15 rule).
  `data/rag/niddk_hypoglycemia.txt`: real extracted text from the NIDDK hypoglycemia page.
  (The ADA site itself blocks automated fetching — hence sourcing from the team's docx.)
- **Structured investigation table** — `data/investigation_table.json`, parsed once from
  `טבלת דאטה.xlsx`. Each record: `{"state": "היפו"|"היפר", "category": str, "cause": str,
  "time_to_effect": str, "explanation": str}`. ~87 real rows already authored by the team
  (exercise timing, insulin dosing errors, pump/site issues, stress, illness, dawn
  phenomenon, Somogyi effect, growth spurts, etc.).
- **Questionnaire** — the 9 yes/no questions from the team's screenshot, verbatim, plus a
  free-text notes field.

## Script: `local_prototype.py`

Standalone script at repo root, run via `python local_prototype.py`, no CLI args.

### 1. `get_anomaly(config) -> tuple[Anomaly, str]`

Calls the existing `AnomalyDetector.check_for_anomalies()` against the test Nightscout site
(`https://ggns2.fly.dev/`, no auth). Wrapped in `try/except` (catches `requests.RequestException`
and generic errors). Returns `(anomaly, "live")` if the call succeeds and finds one, else
`(FALLBACK_ANOMALY, "fallback")`.

`FALLBACK_ANOMALY = Anomaly(type=GLUCOSE_EXTREME, severity=URGENT, message="Glucose reading
of 260 mg/dL, rising fast", details={"glucose": 260, "trend": "rising"})`. Its direction
(high) maps to `state = "היפר"` for table filtering.

### 2. `ask_questionnaire() -> dict`

Loops the 9 questions below via `input()`, accepting `y`/`n` (case-insensitive), re-prompting
on anything else. Then one open `notes` prompt (empty string allowed).

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

### 3. `retrieve_context(anomaly, answers) -> dict`

Zero-cost local retrieval (no LLM/embedding calls):

- Maps anomaly direction to table state (`high` → `היפר`, `low` → `היפו`) and filters
  `investigation_table.json` to matching rows.
- A small hardcoded dict maps each questionnaire key with a `"yes"` answer to Hebrew keyword
  substrings (e.g. `exercised_last_4h` → `["פעילות גופנית", "ספורט", "מאמץ"]`); rows whose
  `category`/`cause` contain any mapped keyword for a "yes"-answered question are selected.
  Cap at the top 3 matches (by table order) to keep context small, per the course's
  "minimize prompt/context size" requirement.
- Pulls the direction-relevant section of the RAG text (hyperglycemia section for high,
  hypoglycemia section for low) via a simple substring split on the source files' section
  headers.
- Returns `{"table_matches": [...], "rag_snippet": "..."}`.

### 4. `print_agent_stub(anomaly, answers, context)`

Prints the exact planned (but not executed) LLM call, in the shape the course's `/api/execute`
`steps` array requires:

```json
{
  "module": "InvestigationAgent",
  "prompt": {
    "system_prompt": "You are a diabetes event investigation assistant for a parent-teen pair. Given a CGM anomaly, structured yes/no answers, relevant cause table rows, and medical reference text, return ONLY a JSON object with two keys: parent_summary (evidence-based possible contributing factors with confidence levels, for the parent) and teen_guidance (short, concrete, actionable next steps for the teen). Do not diagnose.",
    "user_prompt": "<anomaly + answers + context.table_matches + context.rag_snippet, serialized>"
  },
  "response": null
}
```

`module` name (`InvestigationAgent`) is provisional — to be finalized and kept consistent
with the architecture diagram once that's designed (per the course's consistency
requirement).

### 5. `save_record(anomaly, source, answers, context)`

Writes the full record — anomaly, source (`live`/`fallback`), answers, retrieved context,
and the step object from step 4 — to `local_run_output.json`. This is the exact payload
shape needed to wire in the real LLM call later; no rework needed.

### 6. `main()`

Calls the above in order. No additional top-level error handling — this is a manual
developer script, not a service; let unexpected errors surface with their normal traceback.

## Error handling

- Nightscout unreachable/empty → falls back to `FALLBACK_ANOMALY` (per team decision).
- Invalid y/n input → re-prompt, don't crash.
- Missing/unreadable data files (`investigation_table.json`, RAG `.txt` files) → let it
  raise; these are checked into the repo and expected to always be present.

## Testing

Manual: run the script once end-to-end (live Nightscout path if an anomaly happens to be
present, fallback path otherwise), confirm the printed stub and `local_run_output.json`
look right. No automated test suite — this is throwaway scaffolding for the next design
step (wiring in the real LLM call), not production code.
