# API + GUI + Deployment Layer — Design

## Context

The core reasoning pipeline (`agent_pipeline.run_pipeline`, per
`docs/superpowers/specs/2026-08-04-agent-pipeline-design.md` and its implementation plan) is built,
tested (69 automated tests), and verified against real LLMod.ai + Pinecone credentials with two
live end-to-end conversations. What's still missing is the entire "graded surface" the course
(`Project.pdf`) actually inspects: the 4 required HTTP endpoints, a minimal GUI, the architecture
diagram as a PNG, and a Vercel deployment.

This spec covers all of that as one cohesive layer, since the pieces are tightly coupled (the GUI
calls the API; deployment serves both together) and none is independently gradable on its own.

## Decisions made during brainstorming

- **Single FastAPI app, single Vercel serverless entry point.** `api/index.py` hosts one FastAPI
  app with all 4 endpoints plus the GUI's root route; `vercel.json` rewrites every incoming path to
  that one function, and FastAPI's own router dispatches internally. This is the standard pattern
  for deploying FastAPI on Vercel and avoids provisioning 4 separate serverless functions.
- **GUI is one static, self-contained HTML file** (`static/index.html`, inline CSS/JS, no build
  step, no framework) — matches the course's "minimal" requirement and keeps deployment simple.
- **Architecture diagram**: the team's own presentation (`Parent-Teen-Diabetes-Investigation-Agent.pptx`)
  contains the authoritative 5-stage diagram, already extracted to
  `docs/architecture/pipeline_diagram.png`. Its box labels (CGM Event, Structured Questionnaire,
  ReAct Agent, Confidence Classification, Parent Summary) match the implemented module names
  exactly — `/api/model_architecture` serves this file directly, no new diagram needed.
- **Team info**: team name "SugarBuddy"; students Arava Gendelman (`aravag@campus.technion.ac.il`),
  Aya Grabarsky (`ayagrabarsky@campus.technion.ac.il`), Sofia Torgovezky
  (`sofiat@campus.technion.ac.il`). `group_batch_order_number` is not yet known (assigned from the
  course's presentation list) — the endpoint returns the literal string
  `"TODO_FILL_BEFORE_SUBMISSION"` for that field until the real value is available; this is a
  concrete, fully-specified behavior, not an open design question.
- **`prompt_examples` for `/api/agent_info`** use the two real conversations already run live on
  2026-08-05 (glucose spiking to 260 with no follow-up needed; glucose dropping to 65 with no
  follow-up needed) — genuine data, not fabricated. The exact prompt/response/steps content for
  both is reproduced in full in the implementation plan (too long to duplicate here).
- **Parent-decision-to-teen relay is in scope for this build** (not deferred further). It stays
  exactly as originally specced: plain-text pass-through, GUI-only, no LLM call, no backend
  endpoint at all — implemented entirely in the static page's own JavaScript.
- **Deployment**: this spec's implementation prepares all Vercel configuration
  (`vercel.json`, updated `requirements.txt`); the user has an existing Vercel account already
  connected to this GitHub repo and will run/confirm the actual deployment herself.
- **Clients (`llm_client`, `pinecone_index`) are constructed once at module level** in
  `api/index.py`, not per-request, so warm Vercel invocations reuse them instead of rebuilding on
  every call.
- **`/api/execute` never returns anything outside the course's required shape.** The request body
  is parsed manually (not a strict Pydantic model that would trigger FastAPI's own 422 response
  shape) so that a missing/invalid `prompt` field, a `PipelineError`, and any unexpected exception
  all map to the same `{"status": "error", "error": str, "response": null, "steps": []}` contract.

## Scope

Covers: the FastAPI app and its 4 endpoints, the static GUI (including the parent-decision relay),
Vercel deployment configuration. Explicitly out of scope: actually running the Vercel deployment
(the user does this herself), obtaining the real `group_batch_order_number`, any change to the
core reasoning pipeline itself.

## File structure

```
api/
  index.py              # FastAPI app: all 4 endpoints + GUI route; module-level client setup
static/
  index.html             # the entire GUI (HTML + inline CSS + inline JS)
docs/architecture/
  pipeline_diagram.png   # already extracted from the team's presentation
vercel.json              # rewrites all paths to api/index.py
requirements.txt         # + fastapi
tests/
  test_api_team_info.py
  test_api_agent_info.py
  test_api_model_architecture.py
  test_api_execute.py
```

## Endpoint behavior

### `GET /api/team_info`

Returns the static dict described in Decisions above, exactly matching the course's required
shape (`group_batch_order_number`, `team_name`, `students: [{name, email}, ...]`). No LLM call, no
dependency on `agent_pipeline` at all.

### `GET /api/agent_info`

Returns:
- `description` — plain-language explanation of what SugarBuddy does and does not do (investigates
  a glucose anomaly via a 10-question check-in and up to one follow-up question, produces a
  confidence-scored, evidence-based summary for a parent; does not diagnose, does not replace
  medical advice, does not read a live CGM feed as part of grading).
- `purpose` — one or two sentences, matching the design spec's framing (turn CGM anomalies into an
  evidence-based, non-alarming conversation for a parent-teen pair).
- `prompt_template.template` — explains the multi-turn contract: turn 1 describes the glucose
  event (plain language or JSON); turn 2 resends the full conversation so far plus the teen's 10
  answers; turn 3 (only if the agent asks) resends everything again plus the answer to that one
  follow-up question. Concrete numbered-list answer format included, matching what
  `questionnaire.parse_answers` expects.
- `prompt_template.example` — a single starter example: `"glucose spiked to 260 mg/dL and is
  rising fast"`.
- `prompt_examples` — the two real logged conversations from 2026-08-05 live testing, each with
  `prompt` (the turn-1 event description), `full_response` (the actual final `parent_summary`
  text), and `steps` (the real `CGM Event` / `ReAct Agent` / `Confidence Classification` /
  `Parent Summary` step objects exactly as produced).

### `GET /api/model_architecture`

Reads `docs/architecture/pipeline_diagram.png` from disk and returns it with
`Content-Type: image/png`. No caching logic needed — file is small and static per deployment.

### `POST /api/execute`

1. Parse the request body as JSON; extract `prompt`. If missing or not a string, return
   `{"status": "error", "error": "prompt is required", "response": null, "steps": []}` (HTTP 200 —
   the course's contract distinguishes success/failure via the `status` field, not the HTTP status
   code).
2. Call `run_pipeline(prompt, clients)` where `clients` is the module-level `PipelineClients`
   instance built once at import time.
3. On success: call `supabase_log.log_execution(prompt, result["response"], result["steps"])`
   (already non-blocking — failures there are swallowed and printed, never raised) then return
   `{"status": "ok", "error": None, "response": result["response"], "steps": result["steps"]}`.
4. On `PipelineError`: return `{"status": "error", "error": str(e), "response": None, "steps": []}`.
5. On any other exception: return `{"status": "error", "error": f"unexpected error: {e}",
   "response": None, "steps": []}` — never let an unhandled exception produce a raw 500 with a
   shape the course's contract doesn't define.

### `GET /` (GUI)

Returns `static/index.html`'s contents directly (read once at module import time, served via
`HTMLResponse`). No authentication, no redirects — available immediately per the course's
requirement.

## GUI design

Single page, two visible sections, no login, no client-side routing.

**Conversation area:**
- A `<textarea>` + "Run Agent" button.
- A running, append-only log of the conversation: each turn's rendered response text, plus that
  turn's `steps` shown as a `<details>` block per step (native HTML disclosure widget — no JS
  needed for expand/collapse) with `module`, `prompt.system_prompt`, `prompt.user_prompt`, and
  `response` each shown as labeled preformatted blocks.
- JS keeps a single `transcript` string in memory. First click: `transcript = textarea.value`, POST
  `{prompt: transcript}` to `/api/execute`. If the returned `response` contains the literal
  substring `"SUGARBUDDY_CONTEXT"`, the conversation isn't finished — relabel the button "Send
  reply", clear the textarea for the next reply, and on the next click do
  `transcript = transcript + "\n" + response + "\n" + textarea.value` before POSTing again. This is
  the exact accumulation pattern `local_prototype.py` already uses.
- Once a response comes back WITHOUT that marker substring, the conversation is complete: disable
  further replies for this run, and reveal the parent-decision section below.

**Parent-decision section** (hidden until a final `parent_summary` response arrives):
- A `<textarea>` labeled for the parent's decision/instructions, and a "Send to teen" button.
- On click: take the textarea's value and render it verbatim into a separate, clearly-labeled
  "Message to teen" panel on the same page. Pure client-side string handling — no `fetch` call, no
  backend endpoint, no LLM involvement, exactly matching the original design decision that this
  relay never touches the reasoning pipeline.
- A "Start a new event" button resets `transcript` to empty and clears all three areas (conversation
  log, parent-decision box, teen-message panel) to start a fresh CGM event from turn 1.

## Deployment

- `vercel.json`:
  ```json
  {
    "rewrites": [{ "source": "/(.*)", "destination": "/api/index" }]
  }
  ```
- `requirements.txt` gains `fastapi` (Vercel's Python builder detects the ASGI `app` object in
  `api/index.py` natively; no separate ASGI adapter package needed).
- Local dev: `uvicorn api.index:app --reload` (add `uvicorn` to `requirements.txt` too, dev-only
  but harmless to include given this project's existing low-ceremony dependency style).
- Environment variables (`LLMOD_API_KEY`, `LLMOD_BASE_URL`, `PINECONE_API_KEY`,
  `PINECONE_INDEX_NAME`, `SUPABASE_URL`, `SUPABASE_KEY`) must be set in the Vercel project's
  environment settings (same names as `.env`) before the deployed `/api/execute` can make real
  calls — this is a manual step for the user, done through the Vercel dashboard or CLI.
- Actually running the deployment (`vercel --prod`, or confirming the GitHub-integration
  auto-deploy) is done by the user, not automated here.

## Error handling

- `/api/execute` never raises past its own handler — every path (missing prompt, `PipelineError`,
  any other exception) returns the course's exact `{status, error, response, steps}` shape.
- `/api/team_info`, `/api/agent_info` are static data — no failure modes.
- `/api/model_architecture` reads a file that's checked into the repo and always present at deploy
  time; no error handling needed beyond what FastAPI does by default for a missing static file
  (won't happen in practice).
- GUI: if a `fetch` call itself fails (network error, non-200 response), show the raw error text in
  the conversation log rather than failing silently — this is a developer/grader-facing tool, a
  visible error is more useful than a swallowed one.

## Testing

- `TestClient` (FastAPI's test client) for all 4 endpoints, with `run_pipeline` and
  `supabase_log.log_execution` mocked/monkeypatched — no real LLM/Pinecone/Supabase calls in
  automated tests, consistent with the rest of this project.
- `/api/team_info`: assert exact JSON shape and content.
- `/api/agent_info`: assert required top-level keys present, `prompt_examples` has 2 entries, each
  with `prompt`/`full_response`/`steps`.
- `/api/model_architecture`: assert `Content-Type: image/png` and non-empty body starting with the
  PNG magic bytes.
- `/api/execute`: (a) mocked success path returns the `status: ok` shape; (b) mocked
  `PipelineError` returns the `status: error` shape; (c) missing `prompt` in the request body
  returns the `status: error` shape, not FastAPI's default 422.
- GUI: no automated test — manual verification in an actual browser (start the app locally with
  uvicorn, drive a full conversation including a parent-decision entry) before considering the
  work done, per this project's standard for frontend changes.
