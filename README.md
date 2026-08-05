# SugarBuddy

SugarBuddy is a Parent-Teen Diabetes Investigation Agent. It watches a teen's
live CGM (continuous glucose monitor) data via Nightscout, detects
glucose anomalies, and hands them off to a check-in flow so a parent gets a
clear summary instead of raw sensor noise.

## Pipeline

```
CGM Event -> Structured Questionnaire (10 yes/no) -> ReAct Agent (bounded 0-or-1 follow-up)
          -> Confidence Classification -> Parent Summary
```

## Status

- **Anomaly detection** — built (`sugarbuddy_anomaly_detector.py`). Pulls
  entries/treatments from Nightscout and flags three anomaly classes:
  rate-of-change, sensor gaps, and IOB-contextual risk.
- **Core reasoning pipeline** — built and tested (Tasks 1-12 of
  [docs/superpowers/plans/2026-08-04-agent-pipeline.md](docs/superpowers/plans/2026-08-04-agent-pipeline.md)).
  The whole flow runs through one `agent_pipeline.run_pipeline(prompt, clients)`
  entry point across up to three conversational turns; state round-trips in a
  marker embedded in the response, so no server-side session store is needed.
- **Scheduler** — designed, not yet implemented. See
  [docs/superpowers/specs/2026-07-01-anomaly-scheduler-design.md](docs/superpowers/specs/2026-07-01-anomaly-scheduler-design.md)
  for the plan to run detection on a schedule (GitHub Actions -> FastAPI on
  Vercel) with case state persisted in Supabase.
- **FastAPI layer / questionnaire UI** — built and tested. `api/index.py` exposes
  the four required endpoints (`/api/team_info`, `/api/agent_info`,
  `/api/model_architecture`, `/api/execute`) plus a browser GUI at `/`, and the
  whole app deploys to Vercel as a single serverless function.

## Repo layout

- `api/index.py` — the FastAPI app: the four required endpoints and the GUI
  route, wrapping `agent_pipeline.run_pipeline`.
- `static/index.html` — the single-page GUI (run the agent, reply across turns,
  inspect each module's prompts and responses).
- `vercel.json` — Vercel deployment config: routes every path to the function
  and raises its max duration to 300s for the multi-call LLM chain.
- `sugarbuddy_anomaly_detector.py` — `NightscoutClient`, `AnomalyDetector`,
  and `CaseTracker` for the anomaly-detection stage.
- `agent_pipeline.py` — the orchestrator: CGM event parsing, the bounded ReAct
  Agent, Confidence Classification, Parent Summary, and `run_pipeline`.
- `conversation_state.py` — builds and extracts the base64 marker that carries
  conversation state between turns.
- `questionnaire.py` — the 10 Hebrew yes/no questions and answer parsing.
- `llm_client.py` — thin OpenAI-compatible wrapper for LLMod.ai (chat + embeddings).
- `retrieval.py` — Pinecone-backed context retrieval with a keyword fallback.
- `pinecone_ingest.py` — one-time script that creates the index and embeds the
  cause table and RAG reference text into it.
- `supabase_log.py` — non-blocking audit log of pipeline executions.
- `local_prototype.py` — interactive manual smoke test for the full flow.
- `tests/` — pytest suite; every LLM/Pinecone/Supabase call is mocked.
- `docs/superpowers/` — design specs and implementation plans.

## Running

```
pip install -r requirements.txt
cp .env.example .env   # then fill in the values
python -m pytest tests/ -v
python local_prototype.py   # manual end-to-end smoke test (makes real API calls)
```

### Running the API + GUI locally

```
uvicorn api.index:app --reload
```

Then open <http://127.0.0.1:8000/> for the GUI. The endpoints are served from the
same app: `/api/team_info`, `/api/agent_info`, `/api/model_architecture`, and
`POST /api/execute` (`{"prompt": "..."}`). Using the GUI or `/api/execute` makes
real LLM calls, so `.env` must be filled in.
