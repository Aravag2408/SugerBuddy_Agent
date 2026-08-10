# Full-Pipeline Structured Logging for `execution_log` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every stage of the SugarBuddy reasoning pipeline (parsed CGM anomaly, questionnaire
answers, retrieved context, ReAct findings, confidence classification, parent summary, follow-up
question/answer) land in its own queryable column on the `execution_log` Supabase table, instead of
only being reconstructable by parsing nested JSON inside the existing `steps` trace.

**Architecture:** `agent_pipeline.run_pipeline` already holds every one of these values as a local
variable at the moment each stage runs. A new `_build_log_fields` helper assembles a fully-keyed
dict (11 keys, defaulting to `None`) at each of `run_pipeline`'s three return points; `_finalize`
receives that dict and fills in the two keys only it can produce (`confidence_result`,
`parent_summary`) before returning it. `run_pipeline`'s result dict gains one new key, `log_fields`,
alongside the existing `response`/`steps`. `api/index.py` reads that key and passes it straight
through to `supabase_log.log_execution`, which maps it onto 11 new nullable columns.

**Tech Stack:** Python 3.13, FastAPI, pytest, Supabase (Postgres + PostgREST), no new dependencies.

## Global Constraints

- No conversation/session correlation across turns — one `execution_log` row per API call, matching
  the existing behavior; do not introduce a `conversation_id`.
- jsonb-valued fields (`anomaly`, `questionnaire_answers`, `retrieved_context`, `react_findings`,
  `confidence_result`) must be inserted via `json.dumps(value, ensure_ascii=False)` when not `None`,
  matching the existing `steps` column's treatment, so Hebrew text stays human-readable in the
  Supabase Table Editor instead of `\uXXXX`-escaped.
- `log_execution`'s new 4th parameter (`log_fields`) has no default — there is exactly one caller
  and it always has the data. Do not add a backwards-compatible default.
- The migration is a **new** file (`supabase/002_add_pipeline_fields.sql`), never edit the original
  `supabase/migration.sql`.
- Applying the migration to the live Supabase project is a **manual step for the user** — no tool
  in this environment has DDL access to that database (only `SUPABASE_URL`/`SUPABASE_KEY`, which are
  PostgREST/REST credentials and cannot run `ALTER TABLE`).

---

### Task 1: Migration file for the new columns

**Files:**
- Create: `supabase/002_add_pipeline_fields.sql`

**Interfaces:**
- Produces: 11 new nullable columns on `execution_log` — `stage text`, `anomaly jsonb`,
  `questionnaire_answers jsonb`, `notes text`, `retrieved_context jsonb`, `react_findings jsonb`,
  `need_more_info boolean`, `confidence_result jsonb`, `parent_summary text`,
  `followup_question text`, `followup_answer text`. All later tasks assume these exact names.

- [ ] **Step 1: Write the migration file**

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

- [ ] **Step 2: Commit**

```bash
git add supabase/002_add_pipeline_fields.sql
git commit -m "Add migration for execution_log pipeline columns"
```

- [ ] **Step 3: Manual verification (cannot be automated from this environment)**

Tell the user to paste the file's contents into the Supabase project's SQL Editor (same place the
original `execution_log` table was created) and run it. Verify with:

```sql
select column_name from information_schema.columns where table_name = 'execution_log';
```

Expected: the 5 original columns (`id`, `prompt`, `response`, `steps`, `created_at`) plus the 11 new
ones above, 16 total. Do not proceed to treat this task as done until the user confirms this ran —
the code in later tasks will insert into these columns, and Task 4's `_finalize`/`run_pipeline`
changes are exercised entirely by mocked tests, but the *real* deployed `/api/execute` needs the
columns to exist or every real logging call will fail (silently — see the existing
`except Exception` in `supabase_log.log_execution`, unchanged by this plan).

---

### Task 2: `_build_log_fields` helper in `agent_pipeline.py`

**Files:**
- Modify: `agent_pipeline.py` (insert after `_retrieve_context`, i.e. after line 192, before the
  blank lines preceding `_finalize` at line 195 — confirm exact line numbers with
  `grep -n "_finalize\|_retrieve_context" agent_pipeline.py` before editing, since unrelated
  upstream commits may have shifted them further)
- Test: `tests/test_agent_pipeline_finalize.py`

**Interfaces:**
- Produces: `_build_log_fields(stage: str, anomaly: dict, **overrides) -> dict` — returns a dict with
  exactly these 11 keys, `None`-valued unless overridden: `stage`, `anomaly`,
  `questionnaire_answers`, `notes`, `retrieved_context`, `react_findings`, `need_more_info`,
  `confidence_result`, `parent_summary`, `followup_question`, `followup_answer`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_pipeline_finalize.py`, extending the existing import block:

```python
from agent_pipeline import (
    CONFIDENCE_SYSTEM_PROMPT,
    PARENT_SUMMARY_SYSTEM_PROMPT,
    REACT_SYSTEM_PROMPT_BASE,
    _build_log_fields,
    run_confidence_classification,
    run_parent_summary,
)
```

Append these two test functions to the same file:

```python
def test_build_log_fields_defaults_all_keys_to_none():
    fields = _build_log_fields("initial", ANOMALY)

    assert fields == {
        "stage": "initial",
        "anomaly": ANOMALY,
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


def test_build_log_fields_applies_overrides_and_leaves_rest_at_default():
    fields = _build_log_fields(
        "questionnaire_sent", ANOMALY, questionnaire_answers=ANSWERS, need_more_info=True,
    )

    assert fields["stage"] == "questionnaire_sent"
    assert fields["questionnaire_answers"] == ANSWERS
    assert fields["need_more_info"] is True
    assert fields["parent_summary"] is None
    assert fields["followup_question"] is None
```

(`ANOMALY` and `ANSWERS` already exist as module-level constants in this test file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent_pipeline_finalize.py -k build_log_fields -v`
Expected: FAIL with `ImportError: cannot import name '_build_log_fields'`

- [ ] **Step 3: Implement `_build_log_fields`**

In `agent_pipeline.py`, insert this function between `_retrieve_context` (ends line 178) and
`_finalize` (starts line 181):

```python
def _build_log_fields(stage: str, anomaly: dict, **overrides) -> dict:
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent_pipeline_finalize.py -k build_log_fields -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add agent_pipeline.py tests/test_agent_pipeline_finalize.py
git commit -m "Add _build_log_fields helper for structured execution logging"
```

---

### Task 3: Thread `log_fields` through `_finalize`

**Files:**
- Modify: `agent_pipeline.py:195-208` (`_finalize` — verify with
  `grep -n "def _finalize" agent_pipeline.py`, since Task 2 shifts this by however many lines its
  insertion adds)
- Test: `tests/test_agent_pipeline_finalize.py`

**Interfaces:**
- Consumes: `_build_log_fields` from Task 2.
- Produces: `_finalize(anomaly, answers, findings, clients, prior_steps, log_fields) -> dict` — returns
  `{"response": str, "steps": list[dict], "log_fields": dict}` where the passed-in `log_fields` dict
  is mutated in place (its `confidence_result` and `parent_summary` keys filled in) and returned
  under the `"log_fields"` key. Every other key of `log_fields` is untouched. This is a breaking
  signature change — `_finalize` previously took 5 positional args and returned a 2-key dict.

- [ ] **Step 1: Write the failing test**

Add to the imports in `tests/test_agent_pipeline_finalize.py` (extend the block from Task 2):

```python
from agent_pipeline import (
    CONFIDENCE_SYSTEM_PROMPT,
    PARENT_SUMMARY_SYSTEM_PROMPT,
    REACT_SYSTEM_PROMPT_BASE,
    PipelineClients,
    _build_log_fields,
    _finalize,
    run_confidence_classification,
    run_parent_summary,
)
```

Append:

```python
def test_finalize_fills_confidence_and_summary_into_log_fields():
    confidence_response = json.dumps({
        "findings": [{"cause": "exercise", "evidence": "e", "confidence": "medium", "rationale": "r"}],
    })
    summary_response = json.dumps({"parent_summary": "Summary text."})
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content=c))])
        for c in (confidence_response, summary_response)
    ]
    clients = PipelineClients(llm_client=client)
    log_fields = _build_log_fields(
        "questionnaire_sent", ANOMALY, questionnaire_answers=ANSWERS, need_more_info=False,
    )

    result = _finalize(ANOMALY, ANSWERS, FINDINGS, clients, [], log_fields)

    assert result["response"] == "Summary text."
    assert result["steps"][0]["module"] == "Confidence Classification"
    assert result["steps"][1]["module"] == "Parent Summary"
    assert result["log_fields"]["confidence_result"]["findings"][0]["confidence"] == "medium"
    assert result["log_fields"]["parent_summary"] == "Summary text."
    assert result["log_fields"]["stage"] == "questionnaire_sent"  # untouched key survives
    assert result["log_fields"] is log_fields  # mutated in place, not a copy
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_pipeline_finalize.py -k test_finalize_fills -v`
Expected: FAIL with `TypeError: _finalize() missing 1 required positional argument: 'log_fields'`

- [ ] **Step 3: Update `_finalize`**

Replace `agent_pipeline.py:181-194`:

```python
def _finalize(
    anomaly, answers, findings, clients: PipelineClients, prior_steps: list[dict], log_fields: dict,
) -> dict:
    confidence_result, confidence_step = run_confidence_classification(
        anomaly, answers, findings, clients.llm_client
    )
    summary_result, summary_step = run_parent_summary(
        anomaly, answers, confidence_result.get("findings") or [], clients.llm_client
    )
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_pipeline_finalize.py -v`
Expected: PASS (all tests in the file, including Task 2's)

- [ ] **Step 5: Commit**

```bash
git add agent_pipeline.py tests/test_agent_pipeline_finalize.py
git commit -m "Thread log_fields through _finalize"
```

---

### Task 4: Wire `log_fields` through `run_pipeline`'s three return points

**Files:**
- Modify: `agent_pipeline.py:211-252` (`run_pipeline` — verify with
  `grep -n "def run_pipeline" agent_pipeline.py`, since Tasks 2-3 shift this further)
- Test: `tests/test_agent_pipeline_run_pipeline.py`

**Interfaces:**
- Consumes: `_build_log_fields` (Task 2), `_finalize(anomaly, answers, findings, clients, prior_steps, log_fields)` (Task 3).
- Produces: `run_pipeline(prompt, clients) -> dict` now always includes a `"log_fields"` key
  alongside the existing `"response"`/`"steps"`. This is the contract `api/index.py` (Task 6) reads
  from.

This task changes `run_pipeline` itself (no other file consumes `_finalize` or `_build_log_fields`
directly), so this task's tests are the existing `run_pipeline` scenario tests, extended with
`log_fields` assertions.

- [ ] **Step 1: Write the failing test updates**

In `tests/test_agent_pipeline_run_pipeline.py`, extend these four existing test functions with the
assertions below (added at the end of each function, nothing else in the function changes).

`test_turn1_fresh_prompt_returns_questionnaire` gains:

```python
    assert result["log_fields"] == {
        "stage": "initial",
        "anomaly": ANOMALY,
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
```

`test_turn2_no_followup_returns_final_summary` gains:

```python
    assert result["log_fields"] == {
        "stage": "questionnaire_sent",
        "anomaly": ANOMALY,
        "questionnaire_answers": dict.fromkeys(ALL_TEN_ANSWERS, True),
        "notes": "",
        "retrieved_context": {"table_matches": [], "rag_snippet": ""},
        "react_findings": [{"cause": "exercise", "evidence": "e", "source": "answers"}],
        "need_more_info": False,
        "confidence_result": {
            "findings": [{"cause": "exercise", "evidence": "e", "confidence": "medium", "rationale": "r"}],
        },
        "parent_summary": "Event recap. Possible reason: exercise (medium confidence). Suggestion: hydrate.",
        "followup_question": None,
        "followup_answer": None,
    }
```

`test_turn2_with_followup_returns_question_not_summary` gains:

```python
    assert result["log_fields"] == {
        "stage": "questionnaire_sent",
        "anomaly": ANOMALY,
        "questionnaire_answers": dict.fromkeys(ALL_TEN_ANSWERS, True),
        "notes": "",
        "retrieved_context": {"table_matches": [], "rag_snippet": ""},
        "react_findings": [],
        "need_more_info": True,
        "confidence_result": None,
        "parent_summary": None,
        "followup_question": "כמה זמן אחרי האוכל מדדת?",
        "followup_answer": None,
    }
```

`test_turn3_after_followup_returns_final_summary` gains:

```python
    assert result["log_fields"] == {
        "stage": "followup_sent",
        "anomaly": ANOMALY,
        "questionnaire_answers": ALL_TEN_ANSWERS,
        "notes": "",
        "retrieved_context": {"table_matches": [], "rag_snippet": ""},
        "react_findings": [{"cause": "late meal", "evidence": "e", "source": "answers"}],
        "need_more_info": False,
        "confidence_result": {
            "findings": [{"cause": "late meal", "evidence": "e", "confidence": "high", "rationale": "r"}],
        },
        "parent_summary": "Final summary text.",
        "followup_question": "כמה זמן אחרי האוכל מדדת?",
        "followup_answer": "כעשר דקות אחרי",
    }
```

`test_chained_real_transcript_reaches_final_summary` gains, right after its existing final
assertions:

```python
    assert turn3["log_fields"]["followup_question"] == "כמה זמן אחרי האוכל מדדת?"
    assert turn3["log_fields"]["followup_answer"] == "כעשר דקות אחרי"
    assert turn3["log_fields"]["parent_summary"] == "Chained final summary."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent_pipeline_run_pipeline.py -v`
Expected: FAIL on the 5 modified tests with `KeyError: 'log_fields'`

- [ ] **Step 3: Update `run_pipeline`**

Replace `agent_pipeline.py:197-238`:

```python
def run_pipeline(prompt: str, clients: PipelineClients) -> dict:
    state = extract_conversation_state(prompt)

    if state is None or state.stage not in ("questionnaire_sent", "followup_sent"):
        anomaly, steps = parse_cgm_event(prompt, clients.llm_client)
        return {
            "response": format_questionnaire_prompt(anomaly),
            "steps": steps,
            "log_fields": _build_log_fields("initial", anomaly),
        }

    # The marker is client-held and comes back unvalidated on turns 2 and 3, so
    # re-validate the anomaly it carries before it reaches retrieval (where an
    # unexpected direction would otherwise raise a bare KeyError).
    if not _valid_anomaly_dict(state.anomaly):
        raise PipelineError("conversation state carries an invalid anomaly")

    if state.stage == "questionnaire_sent":
        answers, notes = parse_answers(state.reply_text)
        context = _retrieve_context(state.anomaly, answers, clients)
        result, react_step = run_react_agent(state.anomaly, answers, notes, context, clients.llm_client)
        react_findings = result.get("findings") or []

        if result.get("need_more_info"):
            followup_question = result.get("followup_question")
            if not isinstance(followup_question, str) or not followup_question.strip():
                raise PipelineError(
                    "ReAct Agent requested a follow-up but did not provide a question"
                )
            marker = build_marker(
                "followup_sent", anomaly=state.anomaly, answers=answers, notes=notes,
                followup_question=followup_question,
            )
            log_fields = _build_log_fields(
                "questionnaire_sent", state.anomaly, questionnaire_answers=answers, notes=notes,
                retrieved_context=context, react_findings=react_findings, need_more_info=True,
                followup_question=followup_question,
            )
            return {
                "response": f"{followup_question}\n\n{marker}",
                "steps": [react_step],
                "log_fields": log_fields,
            }

        log_fields = _build_log_fields(
            "questionnaire_sent", state.anomaly, questionnaire_answers=answers, notes=notes,
            retrieved_context=context, react_findings=react_findings, need_more_info=False,
        )
        return _finalize(state.anomaly, answers, react_findings, clients, [react_step], log_fields)

    # state.stage == "followup_sent"
    followup_answer = state.reply_text
    answers = state.answers or {}
    context = _retrieve_context(state.anomaly, answers, clients)
    result, react_step = run_react_agent(
        state.anomaly, answers, state.notes, context, clients.llm_client,
        followup={"question": state.followup_question, "answer": followup_answer},
        allow_followup=False,
    )
    react_findings = result.get("findings") or []
    log_fields = _build_log_fields(
        "followup_sent", state.anomaly, questionnaire_answers=answers, notes=state.notes,
        retrieved_context=context, react_findings=react_findings, need_more_info=False,
        followup_question=state.followup_question, followup_answer=followup_answer,
    )
    return _finalize(state.anomaly, answers, react_findings, clients, [react_step], log_fields)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent_pipeline_run_pipeline.py -v`
Expected: PASS (all tests in the file — the 5 modified plus all untouched ones, since they only add
assertions on a new key and don't change behavior of `response`/`steps`)

- [ ] **Step 5: Commit**

```bash
git add agent_pipeline.py tests/test_agent_pipeline_run_pipeline.py
git commit -m "Return log_fields from all three run_pipeline branches"
```

---

### Task 5: `supabase_log.log_execution` accepts and stores `log_fields`

**Files:**
- Modify: `supabase_log.py`
- Test: `tests/test_supabase_log.py`

**Interfaces:**
- Consumes: a fully-keyed `log_fields` dict shaped like `_build_log_fields`'s output (Task 2) — this
  task does not import `agent_pipeline`, it just documents the expected shape via tests.
- Produces: `log_execution(prompt: str, response: str | None, steps: list[dict], log_fields: dict) -> None`
  — breaking signature change, 4th parameter required, no default.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_supabase_log.py`:

```python
import json

import supabase_log


def _sample_log_fields(**overrides):
    fields = {
        "stage": "initial",
        "anomaly": {
            "type": "glucose_extreme", "severity": "urgent", "direction": "high",
            "message": "m", "details": {},
        },
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


def test_log_execution_swallows_client_construction_errors(monkeypatch):
    def raise_error():
        raise RuntimeError("supabase down")

    monkeypatch.setattr(supabase_log, "_get_client", raise_error)

    supabase_log.log_execution("prompt", "response", [{"module": "x"}], _sample_log_fields())  # must not raise


def test_log_execution_inserts_expected_payload(monkeypatch):
    calls = {}

    class FakeTable:
        def insert(self, payload):
            calls["payload"] = payload
            return self

        def execute(self):
            calls["executed"] = True

    class FakeClient:
        def table(self, name):
            calls["table_name"] = name
            return FakeTable()

    monkeypatch.setattr(supabase_log, "_get_client", lambda: FakeClient())

    log_fields = _sample_log_fields()
    supabase_log.log_execution("prompt text", "response text", [{"module": "CGM Event"}], log_fields)

    assert calls["table_name"] == "execution_log"
    assert calls["payload"]["prompt"] == "prompt text"
    assert calls["payload"]["response"] == "response text"
    assert '"module": "CGM Event"' in calls["payload"]["steps"]
    assert calls["payload"]["stage"] == "initial"
    assert json.loads(calls["payload"]["anomaly"]) == log_fields["anomaly"]
    assert calls["payload"]["questionnaire_answers"] is None
    assert calls["payload"]["notes"] is None
    assert calls["payload"]["need_more_info"] is None
    assert calls["executed"] is True


def test_log_execution_encodes_hebrew_jsonb_fields_without_ascii_escaping(monkeypatch):
    calls = {}

    class FakeTable:
        def insert(self, payload):
            calls["payload"] = payload
            return self

        def execute(self):
            pass

    class FakeClient:
        def table(self, name):
            return FakeTable()

    monkeypatch.setattr(supabase_log, "_get_client", lambda: FakeClient())

    log_fields = _sample_log_fields(
        stage="questionnaire_sent",
        questionnaire_answers={"ate_recently": True},
        notes="הערה בעברית",
        retrieved_context={"table_matches": [], "rag_snippet": "טקסט"},
        react_findings=[{"cause": "מתח", "evidence": "e", "source": "answers"}],
        need_more_info=False,
        confidence_result={"findings": [{"cause": "מתח", "confidence": "medium"}]},
        parent_summary="סיכום בעברית",
        followup_question="שאלה?",
        followup_answer="תשובה",
    )

    supabase_log.log_execution("p", "r", [], log_fields)

    payload = calls["payload"]
    assert "מתח" in payload["react_findings"]
    assert "\\u" not in payload["react_findings"]
    assert payload["notes"] == "הערה בעברית"
    assert payload["parent_summary"] == "סיכום בעברית"
    assert payload["followup_question"] == "שאלה?"
    assert payload["followup_answer"] == "תשובה"
    assert payload["need_more_info"] is False
    assert json.loads(payload["confidence_result"])["findings"][0]["cause"] == "מתח"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_supabase_log.py -v`
Expected: FAIL — `TypeError: log_execution() missing 1 required positional argument: 'log_fields'`

- [ ] **Step 3: Update `supabase_log.py`**

Replace the full file contents:

```python
"""Non-blocking audit log of /api/execute calls. Logging failures must
never propagate to the caller — this is a side effect, not part of the
pipeline's contract.

SUPABASE_KEY must be the service-role key and must stay server-side only:
execution_log has row level security enabled with a service-role-only policy
(see supabase/migration.sql), so the anon/public key cannot insert here.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

import config

_client = None


def _get_client():
    global _client
    if _client is None:
        from supabase import create_client
        _client = create_client(
            config.require(config.SUPABASE_URL, "SUPABASE_URL"),
            config.require(config.SUPABASE_KEY, "SUPABASE_KEY"),
        )
    return _client


def _dump(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)


def log_execution(prompt: str, response: str | None, steps: list[dict], log_fields: dict) -> None:
    try:
        client = _get_client()
        client.table("execution_log").insert({
            "prompt": prompt,
            "response": response,
            "steps": json.dumps(steps, ensure_ascii=False),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "stage": log_fields["stage"],
            "anomaly": _dump(log_fields["anomaly"]),
            "questionnaire_answers": _dump(log_fields["questionnaire_answers"]),
            "notes": log_fields["notes"],
            "retrieved_context": _dump(log_fields["retrieved_context"]),
            "react_findings": _dump(log_fields["react_findings"]),
            "need_more_info": log_fields["need_more_info"],
            "confidence_result": _dump(log_fields["confidence_result"]),
            "parent_summary": log_fields["parent_summary"],
            "followup_question": log_fields["followup_question"],
            "followup_answer": log_fields["followup_answer"],
        }).execute()
    except Exception as e:
        print(f"[supabase_log] failed to log execution (non-fatal): {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_supabase_log.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add supabase_log.py tests/test_supabase_log.py
git commit -m "Store full pipeline log_fields on execution_log inserts"
```

---

### Task 6: `api/index.py` passes `log_fields` through to `log_execution`

**Files:**
- Modify: `api/index.py:487-500` (inside the `/api/execute` handler)
- Test: `tests/test_api_execute.py`

**Interfaces:**
- Consumes: `result["log_fields"]` from `run_pipeline` (Task 4); `log_execution(prompt, response, steps, log_fields)` (Task 5).

- [ ] **Step 1: Write the failing test updates**

In `tests/test_api_execute.py`, update `test_execute_success_returns_ok_shape`'s `fake_result` to
include a `log_fields` key (needed because the real handler will now do
`result["log_fields"]`, which would `KeyError` on a dict missing that key):

```python
def test_execute_success_returns_ok_shape(monkeypatch):
    fake_result = {
        "response": "some response text",
        "steps": [{"module": "CGM Event", "prompt": {"system_prompt": "s", "user_prompt": "u"}, "response": {}}],
        "log_fields": {
            "stage": "initial",
            "anomaly": {
                "type": "glucose_extreme", "severity": "urgent", "direction": "high",
                "message": "m", "details": {},
            },
            "questionnaire_answers": None,
            "notes": None,
            "retrieved_context": None,
            "react_findings": None,
            "need_more_info": None,
            "confidence_result": None,
            "parent_summary": None,
            "followup_question": None,
            "followup_answer": None,
        },
    }
    monkeypatch.setattr(api_index, "_get_clients", lambda: MagicMock())
    monkeypatch.setattr(api_index, "run_pipeline", lambda prompt, clients: fake_result)
    monkeypatch.setattr(api_index, "log_execution", lambda *a, **kw: None)

    response = client.post("/api/execute", json={"prompt": "test prompt"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "error": None,
        "response": "some response text",
        "steps": fake_result["steps"],
    }
```

Update `test_execute_prompt_exactly_at_limit_is_accepted`'s `run_pipeline` stub the same way:

```python
def test_execute_prompt_exactly_at_limit_is_accepted(monkeypatch):
    """The cap is a ceiling, not an off-by-one wall: a prompt of exactly
    MAX_PROMPT_CHARS still runs."""
    monkeypatch.setattr(api_index, "_get_clients", lambda: MagicMock())
    monkeypatch.setattr(
        api_index, "run_pipeline",
        lambda prompt, clients: {
            "response": "ok",
            "steps": [],
            "log_fields": {
                "stage": "initial", "anomaly": {}, "questionnaire_answers": None, "notes": None,
                "retrieved_context": None, "react_findings": None, "need_more_info": None,
                "confidence_result": None, "parent_summary": None, "followup_question": None,
                "followup_answer": None,
            },
        },
    )
    monkeypatch.setattr(api_index, "log_execution", lambda *a, **kw: None)

    response = client.post("/api/execute", json={"prompt": "x" * api_index.MAX_PROMPT_CHARS})

    assert response.json()["status"] == "ok"
```

Add a new test, right after `test_execute_success_returns_ok_shape`, that verifies the plumbing
itself:

```python
def test_execute_success_passes_log_fields_to_log_execution(monkeypatch):
    fake_log_fields = {
        "stage": "initial",
        "anomaly": {
            "type": "glucose_extreme", "severity": "urgent", "direction": "high",
            "message": "m", "details": {},
        },
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
    fake_result = {"response": "r", "steps": [], "log_fields": fake_log_fields}
    monkeypatch.setattr(api_index, "_get_clients", lambda: MagicMock())
    monkeypatch.setattr(api_index, "run_pipeline", lambda prompt, clients: fake_result)
    logged_calls = []
    monkeypatch.setattr(api_index, "log_execution", lambda *a: logged_calls.append(a))

    client.post("/api/execute", json={"prompt": "test prompt"})

    assert logged_calls == [("test prompt", "r", [], fake_log_fields)]
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `python -m pytest tests/test_api_execute.py -k passes_log_fields -v`
Expected: FAIL — `AssertionError` (current handler calls `log_execution(prompt, response_text, steps)`, a 3-tuple, not the expected 4-tuple)

- [ ] **Step 3: Update `api/index.py`**

Replace `api/index.py:487-500` (the body of the `try` block through the final `return` in
`/api/execute`):

```python
    try:
        clients = _get_clients()
        result = run_pipeline(prompt, clients)
        response_text = result["response"]
        steps = result["steps"]
        log_fields = result["log_fields"]
    except PipelineError as e:
        return JSONResponse({"status": "error", "error": str(e), "response": None, "steps": []})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"unexpected error: {e}", "response": None, "steps": []})

    log_execution(prompt, response_text, steps, log_fields)
    return JSONResponse(
        {"status": "ok", "error": None, "response": response_text, "steps": steps}
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_execute.py -v`
Expected: PASS (all tests in the file — including
`test_two_real_execute_calls_run_the_real_pipeline_end_to_end`, which exercises the real
`run_pipeline` and therefore now also exercises real `log_fields` construction end-to-end)

- [ ] **Step 5: Commit**

```bash
git add api/index.py tests/test_api_execute.py
git commit -m "Pass log_fields from run_pipeline through to log_execution"
```

---

### Task 7: Full-suite verification and rollout note

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest -v`
Expected: PASS, 0 failures. This project has no other callers of `run_pipeline`, `_finalize`, or
`log_execution` outside the files touched in Tasks 1–6, so a clean full-suite run confirms nothing
else in the codebase broke.

- [ ] **Step 2: Confirm the migration has actually been applied**

If Task 1's Step 3 (pasting `supabase/002_add_pipeline_fields.sql` into the Supabase SQL Editor)
hasn't been done yet, do it now — the code changes in this plan are inert on the live deployment
until those columns exist. Re-run the verification query from Task 1:

```sql
select column_name from information_schema.columns where table_name = 'execution_log';
```

- [ ] **Step 3: Note for the user — optional live verification**

Once the migration is applied and this branch is deployed (or run locally against real
`LLMOD_API_KEY`/`PINECONE_API_KEY`/`SUPABASE_KEY`), one real conversation through `/api/execute` will
populate all 11 new columns. This is an optional manual step for the user to run when they're ready
to spend a live LLM call against the shared budget — not something to do automatically as part of
this plan.
