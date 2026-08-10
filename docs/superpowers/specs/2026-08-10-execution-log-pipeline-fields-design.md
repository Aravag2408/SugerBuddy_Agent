# Full-Pipeline Structured Logging for `execution_log` — Design

## Context

`execution_log` (the Supabase table that `supabase_log.log_execution` writes to on every successful
`/api/execute` call) was defined in `supabase/migration.sql` but had never actually been run against
the live `sugarbuddy` Supabase project — the Table Editor showed no tables at all. The user ran that
migration manually on 2026-08-10, creating the base table (`id`, `prompt`, `response`, `steps jsonb`,
`created_at`).

That base schema captures the raw turn (`prompt`, `response`) and a JSON trace of every LLM call
(`steps`), but the meaningful intermediate pipeline data — the parsed CGM anomaly, the teen's Yes/No
questionnaire answers, the retrieved RAG context, the ReAct agent's findings, the confidence
classification, the follow-up question/answer, the final parent summary — is only reachable by
parsing nested (and in one case double-encoded) JSON inside `steps`. The user wants this data
directly queryable as real columns, covering every stage of the pipeline for every logged turn, not
just what happens to be reconstructable from the LLM call trace.

## Decisions made during brainstorming

- **One log row per API call/turn, not one row per multi-turn conversation.** There is currently no
  conversation/session identifier anywhere in the system — conversation state round-trips via an
  opaque base64 marker embedded in the response text (`conversation_state.py`), echoed back
  unvalidated by the client on the next turn. Introducing a `conversation_id` to correlate rows
  across turns was considered and explicitly deferred as bigger scope than this task needs.
- **Full column list (11 new columns)**, not a trimmed subset — see Schema below. The user confirmed
  the complete list covers what they want rather than a reduced version.
- **Fields are computed inline inside `agent_pipeline.run_pipeline` / `_finalize`**, where the data
  already exists as local variables at the moment each stage runs, rather than reverse-parsed from
  the already-returned `steps` JSON after the fact. Parsing `steps` back apart would duplicate
  knowledge of each step's internal shape in a second place (`supabase_log.py`) and silently break if
  a module's prompt shape ever changes.
- **New additive migration file**, `supabase/002_add_pipeline_fields.sql`, using
  `alter table ... add column if not exists` for every new column — rather than editing the original
  `migration.sql`. This keeps a visible history of what's actually been run against the shared
  production Supabase project, and each statement stays independently re-runnable.
- **jsonb-valued fields are explicitly `json.dumps(value, ensure_ascii=False)` before insert**,
  matching the existing treatment of the `steps` column — so Hebrew text inside `anomaly`,
  `questionnaire_answers`, `retrieved_context`, `react_findings`, and `confidence_result` stays
  human-readable in the Supabase Table Editor / SQL Editor instead of `\uXXXX`-escaped.
- **`log_execution` gains a required 4th parameter, `log_fields`** — no backwards-compatible default.
  There is exactly one caller (`api/index.py`) and it always has the data available by the time it
  calls `log_execution`.

## Scope

Covers: the new migration file; `agent_pipeline.py` (`_build_log_fields` helper, `_finalize`'s
signature, all three `run_pipeline` return points); `supabase_log.py` (`log_execution`'s signature
and insert payload); `api/index.py` (passing the new field through); the existing test files that
exercise all of the above.

Explicitly out of scope: correlating multi-turn conversations into a single row; any change to
`run_pipeline`'s existing `response`/`steps` contract; any UI/dashboard for browsing the log
(Supabase's own Table Editor / SQL Editor is the viewer).

## Schema

`execution_log` gains 11 new nullable columns:

| column                  | type    | populated when |
|--------------------------|---------|-----------------|
| `stage`                  | text    | always — `'initial'` \| `'questionnaire_sent'` \| `'followup_sent'` |
| `anomaly`                 | jsonb   | always — every successful run has a parsed CGM anomaly by the time it's logged |
| `questionnaire_answers`   | jsonb   | null on `'initial'`; the parsed Yes/No answers dict otherwise |
| `notes`                   | text    | null on `'initial'`; free-text notes parsed from the questionnaire reply otherwise |
| `retrieved_context`       | jsonb   | null on `'initial'`; the RAG/table-lookup dict fed to the ReAct agent otherwise |
| `react_findings`          | jsonb   | null on `'initial'`; `result.get("findings") or []` otherwise (may be an empty list) |
| `need_more_info`          | boolean | null on `'initial'`; `True`/`False` otherwise |
| `confidence_result`       | jsonb   | null unless this row reached `_finalize` (i.e. `need_more_info` is `False`) |
| `parent_summary`          | text    | null unless this row reached `_finalize` |
| `followup_question`       | text    | null on `'initial'`; the newly-asked question when `need_more_info` is `True` on a `'questionnaire_sent'` row; the previously-asked question (echoed from state) on a `'followup_sent'` row |
| `followup_answer`         | text    | null except on `'followup_sent'` rows, where it's the teen's answer text (`state.reply_text`) |

Migration (`supabase/002_add_pipeline_fields.sql`):

```sql
alter table execution_log
    add column if not exists stage text,
    add column if not exists anomaly jsonb,
    add column if not exists questionnaire_answers jsonb,
    add column if not exists notes text,
    add column if not exists retrieved_context jsonb,
    add column if not exists react_findings jsonb,
    add column if not exists need_more_info boolean,
    add column if not exists confidence_result jsonb,
    add column if not exists parent_summary text,
    add column if not exists followup_question text,
    add column if not exists followup_answer text;
```

## Pipeline changes (`agent_pipeline.py`)

A new helper builds a fully-keyed dict (all 11 keys always present, defaulting to `None`) so no
downstream code ever needs to guess which keys exist:

```python
def _build_log_fields(stage, anomaly, **overrides) -> dict:
    fields = {
        "stage": stage,
        "anomaly": anomaly,
        "questionnaire_answers": None,
        "notes": None,
        "retrieved_context": None,
        "react_findings": None,
        "need_more_info": None,
        "confidence_result": None,
        "parent_summary": None,
        "followup_question": None,
        "followup_answer": None,
    }
    fields.update(overrides)
    return fields
```

`_finalize`'s signature changes to accept and complete a partial `log_fields` dict rather than
returning a bare `{"response", "steps"}`:

```python
def _finalize(anomaly, answers, findings, clients, prior_steps, log_fields) -> dict:
    confidence_result, confidence_step = run_confidence_classification(...)
    summary_result, summary_step = run_parent_summary(...)
    parent_summary = summary_result.get("parent_summary")
    if not isinstance(parent_summary, str) or not parent_summary.strip():
        raise PipelineError("Parent Summary did not return the expected text")
    log_fields["confidence_result"] = confidence_result
    log_fields["parent_summary"] = parent_summary
    return {
        "response": parent_summary,
        "steps": prior_steps + [confidence_step, summary_step],
        "log_fields": log_fields,
    }
```

`run_pipeline`'s three return points:

- **Turn 1** (fresh prompt): `_build_log_fields("initial", anomaly)`, returned alongside the existing
  `response`/`steps`.
- **`questionnaire_sent`, follow-up needed**: `_build_log_fields("questionnaire_sent", state.anomaly, questionnaire_answers=answers, notes=notes, retrieved_context=context, react_findings=result.get("findings") or [], need_more_info=True, followup_question=followup_question)`, returned directly (no `_finalize` call on this branch).
- **Either finalize path** (`questionnaire_sent` without follow-up, or `followup_sent`): build the
  partial `log_fields` with `need_more_info=False` and the stage-appropriate
  `questionnaire_answers`/`notes`/`retrieved_context`/`react_findings` (plus `followup_question` and
  `followup_answer` on the `followup_sent` branch), then pass it into `_finalize(...)`, which fills in
  `confidence_result` and `parent_summary` before returning.

## Logging plumbing (`supabase_log.py`, `api/index.py`)

`api/index.py`'s `/api/execute` handler additionally reads `log_fields = result["log_fields"]` and
passes it through: `log_execution(prompt, response_text, steps, log_fields)`.

`supabase_log.log_execution(prompt, response, steps, log_fields)` inserts all existing columns plus
the 11 new ones, using a small helper for jsonb encoding:

```python
def _dump(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)
```

jsonb columns (`anomaly`, `questionnaire_answers`, `retrieved_context`, `react_findings`,
`confidence_result`) go through `_dump`; plain text/boolean columns (`stage`, `notes`,
`parent_summary`, `followup_question`, `followup_answer`, `need_more_info`) are inserted as-is from
`log_fields`.

## Error handling

- Same non-blocking contract as today: any failure inside `log_execution` — including an insert
  against columns that don't exist yet if the migration hasn't been run — is caught and printed by
  the existing `except Exception` in `supabase_log.py`, never raised. A logging failure must never
  break a live conversation turn.
- `_build_log_fields` guarantees `log_fields` always carries all 11 keys, so `log_execution` never
  needs defensive `.get()` calls with fallback values — a missing key would be a bug in
  `agent_pipeline.py`, not a real-world data condition to code around.

## Testing

- `tests/test_agent_pipeline_run_pipeline.py` — existing tests for each of the three branches
  (turn 1, questionnaire_sent-with-followup, questionnaire_sent-direct-finalize, followup_sent) gain
  assertions on `result["log_fields"]`'s contents for that branch.
- `tests/test_agent_pipeline_finalize.py` — a new test calling `_finalize` directly, asserting the
  passed-in `log_fields` dict comes back with `confidence_result` and `parent_summary` filled in and
  every other pre-existing key untouched.
- `tests/test_supabase_log.py` — both existing tests update their `log_execution` call to pass a 4th
  `log_fields` argument; the payload assertion extends to check the new columns are present with the
  expected values, and that `None` values stay `None` (not the string `"null"`).
- `tests/test_api_execute.py` — the `log_execution` monkeypatch/mock call sites update to accept the
  4th argument so the signature change doesn't break them.
