# Agent Reasoning Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core SugarBuddy reasoning pipeline described in
`docs/superpowers/specs/2026-08-04-agent-pipeline-design.md`: a CGM event parsed from a prompt,
a 10-question exchange with the teen, a bounded ReAct Agent (0 or 1 follow-up question),
Confidence Classification, and a Parent Summary — all callable through one `run_pipeline(prompt,
clients)` entry point that a future FastAPI layer will wrap.

**Architecture:** Small, single-responsibility modules at the repo root (matching the existing
flat layout of `sugarbuddy_anomaly_detector.py` / `local_prototype.py`): `config.py` (env/model
constants), `errors.py` (shared exception), `conversation_state.py` (marker embed/extract for
stateless multi-turn), `questionnaire.py` (the 10 questions + answer parsing), `llm_client.py`
(thin OpenAI-compatible wrapper for LLMod.ai), `retrieval.py` (Pinecone retrieval + keyword
fallback), `pinecone_ingest.py` (one-time embedding script), `supabase_log.py` (non-blocking audit
log), and `agent_pipeline.py` (the orchestrator, built up across four tasks). `local_prototype.py`
is rewritten last into an interactive manual smoke-test driver for the whole flow.

**Tech Stack:** Python 3.13, `openai` SDK (pointed at LLMod.ai's OpenAI-compatible endpoint),
`pinecone` SDK v5+, `supabase-py`, `python-dotenv`, `pytest`.

## Global Constraints

- Module names used in LLM-calling steps must be exactly: `CGM Event`, `ReAct Agent`,
  `Confidence Classification`, `Parent Summary` (per spec — these will later feed the
  architecture diagram and `/api/execute`'s `steps` field verbatim).
- Text model: `MB5R2CF-azure/gpt-5.4-mini`. Embedding model: `MB5R2CF-azure/text-embedding-3-small`
  (1536-dimensional output).
- The 10 questionnaire questions must be reproduced verbatim (Hebrew text), in the order given in
  the spec.
- No live network calls in automated tests — every LLM/embedding/Pinecone/Supabase call is mocked.
  Only the final manual smoke test (Task 12) makes real calls, and only once the developer has
  supplied real credentials.
- Keep prompts small (course requirement to minimize context/LLM calls): the Confidence
  Classification and Parent Summary stages receive only the prior stage's structured output, never
  the raw retrieved context again.

---

## Before you start: manual account setup

These cannot be automated by an engineer working through this plan — they require signing up for
external services in a browser. Automated tests in every task below use mocks and do **not**
require any of this to be done first; only Task 12's manual smoke test does.

1. **LLMod.ai** — generate your team's API key through whatever course-provided portal/instructions
   you were given (the assignment PDF only says "each group must create its own LLMod.ai API key,"
   shared across the team). Note the base URL it gives you for API calls.
2. **Pinecone** — sign up at pinecone.io, create an API key. The index itself is created
   *programmatically* by this plan's code (Task 6), so you only need the API key up front.
3. **Supabase** — create a project at supabase.com, note its URL and anon/service key from
   Project Settings → API. You'll run one SQL statement from Task 7 in the SQL Editor once that
   task is reached.

Once you have these, copy `.env.example` (created in Task 1) to `.env` and fill in the values.

---

### Task 1: Project scaffolding — dependencies, env config, shared error type

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `pytest.ini`
- Modify: `.gitignore`
- Create: `config.py`
- Create: `errors.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.require(value, var_name) -> str` (raises `RuntimeError` if `value` is falsy),
  `config.LLMOD_API_KEY`, `config.LLMOD_BASE_URL`, `config.PINECONE_API_KEY`,
  `config.PINECONE_INDEX_NAME`, `config.SUPABASE_URL`, `config.SUPABASE_KEY` (all
  `str | None`, read from env at import time), `config.TEXT_MODEL`, `config.EMBED_MODEL` (fixed
  strings). `errors.PipelineError(Exception)`.

- [ ] **Step 1: Create `requirements.txt`**

```
openai>=1.0.0
pinecone>=5.0.0
supabase>=2.0.0
python-dotenv>=1.0.0
pytest>=8.0.0
```

- [ ] **Step 2: Create `.env.example`**

```
LLMOD_API_KEY=
LLMOD_BASE_URL=
PINECONE_API_KEY=
PINECONE_INDEX_NAME=sugarbuddy-causes
SUPABASE_URL=
SUPABASE_KEY=
```

- [ ] **Step 3: Create `pytest.ini`** (so `import config` etc. resolve from repo root during test collection)

```
[pytest]
pythonpath = .
```

- [ ] **Step 4: Add `.env` to `.gitignore`**

Append a line to the existing `.gitignore` (currently just `local_run_output.json`):

```
local_run_output.json
.env
```

- [ ] **Step 5: Install dependencies**

Run: `pip install -r requirements.txt`

- [ ] **Step 6: Write the failing test for `config.require`**

```python
# tests/test_config.py
import pytest
import config


def test_require_raises_when_value_missing():
    with pytest.raises(RuntimeError, match="FOO_VAR"):
        config.require(None, "FOO_VAR")


def test_require_raises_when_value_empty_string():
    with pytest.raises(RuntimeError, match="FOO_VAR"):
        config.require("", "FOO_VAR")


def test_require_returns_value_when_present():
    assert config.require("abc", "FOO_VAR") == "abc"


def test_model_constants_are_set():
    assert config.TEXT_MODEL == "MB5R2CF-azure/gpt-5.4-mini"
    assert config.EMBED_MODEL == "MB5R2CF-azure/text-embedding-3-small"
```

- [ ] **Step 7: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 8: Create `errors.py`**

```python
class PipelineError(Exception):
    """Raised for any unrecoverable failure in the agent reasoning pipeline.

    The (future) FastAPI layer catches this and maps it to
    {"status": "error", "error": str(e), "response": null, "steps": []}.
    """
```

- [ ] **Step 9: Create `config.py`**

```python
from __future__ import annotations
import os

from dotenv import load_dotenv

load_dotenv()

LLMOD_API_KEY = os.environ.get("LLMOD_API_KEY")
LLMOD_BASE_URL = os.environ.get("LLMOD_BASE_URL")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "sugarbuddy-causes")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

TEXT_MODEL = "MB5R2CF-azure/gpt-5.4-mini"
EMBED_MODEL = "MB5R2CF-azure/text-embedding-3-small"


def require(value: str | None, var_name: str) -> str:
    if not value:
        raise RuntimeError(
            f"{var_name} is not set. Copy .env.example to .env and fill it in."
        )
    return value
```

- [ ] **Step 10: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (4 tests)

- [ ] **Step 11: Commit**

```bash
git add requirements.txt .env.example pytest.ini .gitignore config.py errors.py tests/test_config.py
git commit -m "Add project scaffolding: deps, env config, shared PipelineError"
```

---

### Task 2: Conversation state (stateless multi-turn marker)

**Files:**
- Create: `conversation_state.py`
- Test: `tests/test_conversation_state.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces: `conversation_state.ConversationState` dataclass with fields `stage: str`,
  `anomaly: dict`, `answers: dict | None`, `notes: str`, `followup_question: str | None`,
  `reply_text: str`. `conversation_state.build_marker(stage: str, **fields) -> str`.
  `conversation_state.extract_conversation_state(prompt: str) -> ConversationState | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_conversation_state.py
from conversation_state import build_marker, extract_conversation_state


def test_extract_returns_none_when_no_marker():
    assert extract_conversation_state("just a plain description of an event") is None


def test_build_and_extract_questionnaire_sent_roundtrip():
    anomaly = {"type": "glucose_extreme", "severity": "urgent", "direction": "high",
               "message": "m", "details": {}}
    marker = build_marker("questionnaire_sent", anomaly=anomaly)
    prompt = f"Some questions text\n{marker}\n1. Y 2. N 3. Y"

    state = extract_conversation_state(prompt)

    assert state.stage == "questionnaire_sent"
    assert state.anomaly == anomaly
    assert state.reply_text == "1. Y 2. N 3. Y"


def test_build_and_extract_followup_sent_roundtrip():
    anomaly = {"type": "glucose_extreme", "severity": "urgent", "direction": "high",
               "message": "m", "details": {}}
    answers = {"ate_recently": True}
    marker = build_marker(
        "followup_sent", anomaly=anomaly, answers=answers, notes="some notes",
        followup_question="מתי אכלת?",
    )
    prompt = f"מתי אכלת?\n{marker}\nלפני שעה"

    state = extract_conversation_state(prompt)

    assert state.stage == "followup_sent"
    assert state.anomaly == anomaly
    assert state.answers == answers
    assert state.notes == "some notes"
    assert state.followup_question == "מתי אכלת?"
    assert state.reply_text == "לפני שעה"


def test_extract_uses_last_marker_when_multiple_present():
    anomaly = {"type": "big_gap", "severity": "urgent", "direction": None, "message": "m", "details": {}}
    first_marker = build_marker("questionnaire_sent", anomaly=anomaly)
    second_marker = build_marker("followup_sent", anomaly=anomaly, answers={}, notes="", followup_question="q?")
    prompt = f"{first_marker}\nsome reply\n{second_marker}\nlatest reply"

    state = extract_conversation_state(prompt)

    assert state.stage == "followup_sent"
    assert state.reply_text == "latest reply"


def test_extract_returns_none_on_malformed_marker_json():
    prompt = "<!-- SUGARBUDDY_CONTEXT: {not valid json} -->\nreply"
    assert extract_conversation_state(prompt) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_conversation_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'conversation_state'`

- [ ] **Step 3: Write `conversation_state.py`**

```python
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Optional

MARKER_PREFIX = "<!-- SUGARBUDDY_CONTEXT: "
MARKER_SUFFIX = " -->"

_MARKER_PATTERN = re.compile(
    re.escape(MARKER_PREFIX) + r"(.*?)" + re.escape(MARKER_SUFFIX), re.DOTALL
)


@dataclass
class ConversationState:
    stage: str
    anomaly: dict
    answers: Optional[dict] = None
    notes: str = ""
    followup_question: Optional[str] = None
    reply_text: str = ""


def build_marker(stage: str, **fields) -> str:
    payload = {"stage": stage, **fields}
    return f"{MARKER_PREFIX}{json.dumps(payload, ensure_ascii=False)}{MARKER_SUFFIX}"


def extract_conversation_state(prompt: str) -> ConversationState | None:
    matches = list(_MARKER_PATTERN.finditer(prompt))
    if not matches:
        return None

    last_match = matches[-1]
    try:
        payload = json.loads(last_match.group(1))
    except json.JSONDecodeError:
        return None

    return ConversationState(
        stage=payload.get("stage", ""),
        anomaly=payload.get("anomaly", {}),
        answers=payload.get("answers"),
        notes=payload.get("notes", ""),
        followup_question=payload.get("followup_question"),
        reply_text=prompt[last_match.end():].strip(),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_conversation_state.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add conversation_state.py tests/test_conversation_state.py
git commit -m "Add conversation_state module for stateless multi-turn tracking"
```

---

### Task 3: Questionnaire (10 questions + answer parsing)

**Files:**
- Create: `questionnaire.py`
- Test: `tests/test_questionnaire.py`

**Interfaces:**
- Consumes: `conversation_state.build_marker`, `errors.PipelineError`.
- Produces: `questionnaire.QUESTIONS: list[tuple[str, str]]` (10 entries),
  `questionnaire.format_questionnaire_prompt(anomaly: dict) -> str`,
  `questionnaire.parse_answers(reply_text: str) -> tuple[dict[str, bool], str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questionnaire.py
import pytest
from questionnaire import QUESTIONS, format_questionnaire_prompt, parse_answers
from errors import PipelineError

ANOMALY = {"type": "glucose_extreme", "severity": "urgent", "direction": "high",
           "message": "m", "details": {}}


def test_questions_list_has_ten_entries_in_order():
    assert len(QUESTIONS) == 10
    assert QUESTIONS[0][0] == "ate_recently"
    assert QUESTIONS[9][0] == "finger_stick_or_calibration_recent"
    assert QUESTIONS[9][1] == "האם עשית בדיקה באצבע או כיול לאחרונה?"


def test_format_questionnaire_prompt_includes_all_questions_and_marker():
    text = format_questionnaire_prompt(ANOMALY)
    for i, (_, question_text) in enumerate(QUESTIONS, start=1):
        assert f"{i}. {question_text}" in text
    assert "SUGARBUDDY_CONTEXT" in text
    assert '"stage": "questionnaire_sent"' in text


def test_parse_answers_all_yes_english():
    reply = "\n".join(f"{i}. Y" for i in range(1, 11))
    answers, notes = parse_answers(reply)
    assert all(answers.values())
    assert len(answers) == 10
    assert notes == ""


def test_parse_answers_mixed_hebrew_and_notes():
    reply = "1. כן\n2. לא\n3. Y\n4. N\n5. Yes\n6. No\n7. כן\n8. לא\n9. Y\n10. N\nהערה: ישנתי מאוחר"
    answers, notes = parse_answers(reply)
    assert answers["ate_recently"] is True
    assert answers["carb_count_accurate"] is False
    assert notes == "הערה: ישנתי מאוחר"


def test_parse_answers_raises_when_fewer_than_ten():
    reply = "1. Y\n2. N\n3. Y"
    with pytest.raises(PipelineError, match="numbered Y/N list"):
        parse_answers(reply)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_questionnaire.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'questionnaire'`

- [ ] **Step 3: Write `questionnaire.py`**

```python
from __future__ import annotations
import re

from conversation_state import build_marker
from errors import PipelineError

QUESTIONS: list[tuple[str, str]] = [
    ("ate_recently", "אכלת משהו בתוך השעתיים האחרונות?"),
    ("carb_count_accurate", "האם הזנת כמות מדוייקת של פחמימות או בערך?"),
    ("exercised_last_4h", "רצת, קפצת, או עשית שיעור ספורט ואימון ב-4 השעות האחרונות?"),
    ("stressed_last_30min", "מישהו הרגיז אותך או שהיית בלחץ גדול בחצי השעה האחרונה?"),
    ("drank_water_today", "שתית לפחות 4 כוסות מים במהלך היום?"),
    ("hot_weather_last_30min", "האם היית בחוץ במזג אוויר חם מאוד בחצי השעה האחרונה?"),
    ("correction_dose_last_3h", "החלפת משאבה או לקחת מנת תיקון (או פחמימות מהירות להיפו) ב-3 השעות האחרונות?"),
    ("phone_sensor_check_last_hour", "האם היית צמודה לטלפון הנייד בשעה האחרונה, והאם בדקת שהחיישן והמשאבה מחוברים חזק לעור?"),
    ("accurate_meals_today", "האם אכלת ארוחות מדוייקות היום?"),
    ("finger_stick_or_calibration_recent", "האם עשית בדיקה באצבע או כיול לאחרונה?"),
]

_ANSWER_LINE = re.compile(r"(\d+)\.\s*(Y|N|Yes|No|כן|לא)\b", re.IGNORECASE)
_YES_VALUES = {"y", "yes", "כן"}


def format_questionnaire_prompt(anomaly: dict) -> str:
    lines = [
        "Thanks — before I can investigate, please answer these yes/no questions.",
        'Reply as a numbered list, e.g. "1. Y 2. N 3. Y ...". You may add notes after the list.',
        "",
    ]
    for i, (_, text) in enumerate(QUESTIONS, start=1):
        lines.append(f"{i}. {text}")
    lines.append("")
    lines.append(build_marker("questionnaire_sent", anomaly=anomaly))
    return "\n".join(lines)


def parse_answers(reply_text: str) -> tuple[dict[str, bool], str]:
    matches = list(_ANSWER_LINE.finditer(reply_text))

    found: dict[int, bool] = {}
    for m in matches:
        index = int(m.group(1))
        if 1 <= index <= len(QUESTIONS):
            found[index] = m.group(2).strip().lower() in _YES_VALUES

    if len(found) < len(QUESTIONS):
        raise PipelineError(
            "could not parse all questionnaire answers; reply as a numbered Y/N list"
        )

    answers = {QUESTIONS[i - 1][0]: found[i] for i in found}
    notes = reply_text[matches[-1].end():].strip() if matches else ""
    return answers, notes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_questionnaire.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add questionnaire.py tests/test_questionnaire.py
git commit -m "Add questionnaire module: 10 finalized questions + answer parsing"
```

---

### Task 4: LLM client wrapper (LLMod.ai)

**Files:**
- Create: `llm_client.py`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `config.require`, `config.LLMOD_API_KEY`, `config.LLMOD_BASE_URL`,
  `config.TEXT_MODEL`, `config.EMBED_MODEL`, `errors.PipelineError`.
- Produces: `llm_client.get_llm_client() -> openai.OpenAI`,
  `llm_client.chat_json(client, module: str, system_prompt: str, user_prompt: str) -> tuple[dict, dict]`
  (returns `(parsed_json, step_dict)` where `step_dict = {"module": module, "prompt":
  {"system_prompt": ..., "user_prompt": ...}, "response": parsed_json}`),
  `llm_client.embed_text(client, text: str) -> list[float]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_client.py
import json
import pytest
from unittest.mock import MagicMock

import config
import llm_client
from errors import PipelineError


def _fake_chat_client(content: str):
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=content))
    ]
    return client


def test_get_llm_client_raises_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "LLMOD_API_KEY", None)
    monkeypatch.setattr(config, "LLMOD_BASE_URL", "https://example.test")
    with pytest.raises(RuntimeError, match="LLMOD_API_KEY"):
        llm_client.get_llm_client()


def test_chat_json_parses_response_and_builds_step():
    client = _fake_chat_client('{"foo": "bar"}')

    parsed, step = llm_client.chat_json(client, "CGM Event", "sys prompt", "user prompt")

    assert parsed == {"foo": "bar"}
    assert step == {
        "module": "CGM Event",
        "prompt": {"system_prompt": "sys prompt", "user_prompt": "user prompt"},
        "response": {"foo": "bar"},
    }
    client.chat.completions.create.assert_called_once()
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == config.TEXT_MODEL
    assert call_kwargs["messages"] == [
        {"role": "system", "content": "sys prompt"},
        {"role": "user", "content": "user prompt"},
    ]


def test_chat_json_raises_pipeline_error_on_invalid_json():
    client = _fake_chat_client("not valid json")
    with pytest.raises(PipelineError, match="invalid JSON"):
        llm_client.chat_json(client, "CGM Event", "sys", "user")


def test_chat_json_raises_pipeline_error_on_api_failure():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("connection reset")
    with pytest.raises(PipelineError, match="CGM Event call failed"):
        llm_client.chat_json(client, "CGM Event", "sys", "user")


def test_embed_text_returns_vector():
    client = MagicMock()
    client.embeddings.create.return_value.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    vector = llm_client.embed_text(client, "some text")

    assert vector == [0.1, 0.2, 0.3]
    client.embeddings.create.assert_called_once_with(model=config.EMBED_MODEL, input="some text")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_llm_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm_client'`

- [ ] **Step 3: Write `llm_client.py`**

```python
from __future__ import annotations
import json

from openai import OpenAI

import config
from errors import PipelineError


def get_llm_client() -> OpenAI:
    return OpenAI(
        api_key=config.require(config.LLMOD_API_KEY, "LLMOD_API_KEY"),
        base_url=config.require(config.LLMOD_BASE_URL, "LLMOD_BASE_URL"),
    )


def chat_json(client, module: str, system_prompt: str, user_prompt: str) -> tuple[dict, dict]:
    try:
        completion = client.chat.completions.create(
            model=config.TEXT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content
    except Exception as e:
        raise PipelineError(f"{module} call failed: {e}") from e

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PipelineError(f"{module} returned invalid JSON: {e}") from e

    step = {
        "module": module,
        "prompt": {"system_prompt": system_prompt, "user_prompt": user_prompt},
        "response": parsed,
    }
    return parsed, step


def embed_text(client, text: str) -> list[float]:
    response = client.embeddings.create(model=config.EMBED_MODEL, input=text)
    return response.data[0].embedding
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_llm_client.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add llm_client.py tests/test_llm_client.py
git commit -m "Add llm_client wrapper for LLMod.ai chat + embedding calls"
```

---

### Task 5: Retrieval (Pinecone-backed, keyword fallback)

**Files:**
- Create: `retrieval.py`
- Test: `tests/test_retrieval.py`

**Interfaces:**
- Consumes: `llm_client.embed_text`, `questionnaire.QUESTIONS`, `config.require`,
  `config.PINECONE_API_KEY`, `config.PINECONE_INDEX_NAME`.
- Produces: `retrieval.DATA_DIR`, `retrieval.load_table() -> list[dict]`,
  `retrieval.extract_rag_section(text: str, direction: str) -> str`,
  `retrieval.retrieve_context_keyword(direction: str | None, answers: dict) -> dict`
  (`{"table_matches": [...], "rag_snippet": "..."}`),
  `retrieval.get_pinecone_index()` (raises if unconfigured),
  `retrieval.get_pinecone_index_safe()` (returns `None` on any failure),
  `retrieval.retrieve_context_pinecone(direction, answers, embed_client, pinecone_index) -> dict`
  (same shape, falls back to `retrieve_context_keyword` on any error).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_retrieval.py
from types import SimpleNamespace

import retrieval


def test_retrieve_context_keyword_no_direction_returns_empty():
    assert retrieval.retrieve_context_keyword(None, {}) == {"table_matches": [], "rag_snippet": ""}


def test_retrieve_context_keyword_matches_on_yes_answer(monkeypatch):
    fake_table = [
        {"state": "היפו", "category": "פעילות גופנית", "cause": "ריצה", "explanation": "..."},
        {"state": "היפו", "category": "אחר", "cause": "לא רלוונטי", "explanation": "..."},
    ]
    monkeypatch.setattr(retrieval, "load_table", lambda: fake_table)
    monkeypatch.setattr(retrieval, "RAG_FILES", {"low": []})

    result = retrieval.retrieve_context_keyword("low", {"exercised_last_4h": True})

    assert len(result["table_matches"]) == 1
    assert result["table_matches"][0]["cause"] == "ריצה"


def test_extract_rag_section_splits_on_headers():
    text = "## HYPERGLYCEMIA\nhigh stuff\n## HYPOGLYCEMIA\nlow stuff"
    assert retrieval.extract_rag_section(text, "high") == "high stuff"
    assert retrieval.extract_rag_section(text, "low") == "low stuff"


def test_retrieve_context_pinecone_no_direction_returns_empty():
    result = retrieval.retrieve_context_pinecone(None, {}, embed_client=None, pinecone_index=None)
    assert result == {"table_matches": [], "rag_snippet": ""}


def test_retrieve_context_pinecone_queries_both_namespaces(monkeypatch):
    monkeypatch.setattr(retrieval, "embed_text", lambda client, text: [0.1, 0.2])

    causes_response = SimpleNamespace(matches=[SimpleNamespace(metadata={"cause": "ריצה"})])
    reference_response = SimpleNamespace(matches=[SimpleNamespace(metadata={"text": "some medical text"})])

    class FakeIndex:
        def query(self, vector, top_k, namespace, filter, include_metadata):
            if namespace == "causes":
                assert filter == {"state": {"$eq": "היפו"}}
                return causes_response
            assert namespace == "reference"
            assert filter == {"direction": {"$eq": "low"}}
            return reference_response

    result = retrieval.retrieve_context_pinecone(
        "low", {"exercised_last_4h": True}, embed_client=None, pinecone_index=FakeIndex()
    )

    assert result == {"table_matches": [{"cause": "ריצה"}], "rag_snippet": "some medical text"}


def test_retrieve_context_pinecone_falls_back_on_error(monkeypatch):
    def raise_error(client, text):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(retrieval, "embed_text", raise_error)
    monkeypatch.setattr(
        retrieval, "retrieve_context_keyword",
        lambda direction, answers: {"table_matches": ["fallback"], "rag_snippet": ""},
    )

    result = retrieval.retrieve_context_pinecone("low", {}, embed_client=None, pinecone_index=object())

    assert result == {"table_matches": ["fallback"], "rag_snippet": ""}


def test_get_pinecone_index_safe_returns_none_when_unconfigured(monkeypatch):
    import config
    monkeypatch.setattr(config, "PINECONE_API_KEY", None)
    assert retrieval.get_pinecone_index_safe() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_retrieval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'retrieval'`

- [ ] **Step 3: Write `retrieval.py`**

```python
from __future__ import annotations
import json
from pathlib import Path

import config
from llm_client import embed_text
from questionnaire import QUESTIONS

DATA_DIR = Path(__file__).parent / "data"

STATE_BY_DIRECTION = {"high": "היפר", "low": "היפו"}

KEYWORD_MAP: list[tuple[str, bool, list[str]]] = [
    ("ate_recently", False, ["ארוחות"]),
    ("carb_count_accurate", False, ["פחמימות"]),
    ("exercised_last_4h", True, ["פעילות גופנית"]),
    ("stressed_last_30min", True, ["סטרס", "לחץ"]),
    ("hot_weather_last_30min", True, ["חום", "מזג אוויר"]),
    ("correction_dose_last_3h", True, ["תיקון"]),
    ("phone_sensor_check_last_hour", False, ["טלפון"]),
    ("accurate_meals_today", False, ["ארוחות"]),
]

RAG_FILES: dict[str, list[Path]] = {
    "high": [DATA_DIR / "rag" / "ada_diabetes_association.txt"],
    "low": [
        DATA_DIR / "rag" / "ada_diabetes_association.txt",
        DATA_DIR / "rag" / "niddk_hypoglycemia.txt",
    ],
}


def load_table() -> list[dict]:
    with open(DATA_DIR / "investigation_table.json", encoding="utf-8") as f:
        return json.load(f)


def extract_rag_section(text: str, direction: str) -> str:
    marker = "## HYPERGLYCEMIA" if direction == "high" else "## HYPOGLYCEMIA"
    other_marker = "## HYPOGLYCEMIA" if direction == "high" else "## HYPERGLYCEMIA"
    if marker not in text:
        return ""
    section = text.split(marker, 1)[1]
    if other_marker in section:
        section = section.split(other_marker, 1)[0]
    return section.strip()


def retrieve_context_keyword(direction: str | None, answers: dict) -> dict:
    if direction is None:
        return {"table_matches": [], "rag_snippet": ""}

    state = STATE_BY_DIRECTION[direction]
    table = [row for row in load_table() if row["state"] == state]

    matches: list[dict] = []
    for key, trigger, keywords in KEYWORD_MAP:
        if answers.get(key) != trigger:
            continue
        for row in table:
            haystack = row["category"] + " " + row["cause"]
            if any(kw in haystack for kw in keywords) and row not in matches:
                matches.append(row)

    matches = matches[:3]

    rag_snippet = ""
    for path in RAG_FILES.get(direction, []):
        text = path.read_text(encoding="utf-8")
        rag_snippet += extract_rag_section(text, direction) + "\n\n"

    return {"table_matches": matches, "rag_snippet": rag_snippet.strip()}


def get_pinecone_index():
    from pinecone import Pinecone
    pc = Pinecone(api_key=config.require(config.PINECONE_API_KEY, "PINECONE_API_KEY"))
    return pc.Index(config.PINECONE_INDEX_NAME)


def get_pinecone_index_safe():
    try:
        return get_pinecone_index()
    except Exception:
        return None


def _build_query_text(direction: str, answers: dict) -> str:
    yes_texts = [text for key, text in QUESTIONS if answers.get(key)]
    return f"glucose direction: {direction}. " + " ".join(yes_texts)


def retrieve_context_pinecone(direction, answers, embed_client, pinecone_index) -> dict:
    if direction is None:
        return {"table_matches": [], "rag_snippet": ""}

    try:
        query_text = _build_query_text(direction, answers)
        vector = embed_text(embed_client, query_text)
        state = STATE_BY_DIRECTION[direction]

        causes_result = pinecone_index.query(
            vector=vector, top_k=3, namespace="causes",
            filter={"state": {"$eq": state}}, include_metadata=True,
        )
        table_matches = [match.metadata for match in causes_result.matches]

        reference_result = pinecone_index.query(
            vector=vector, top_k=2, namespace="reference",
            filter={"direction": {"$eq": direction}}, include_metadata=True,
        )
        rag_snippet = "\n\n".join(match.metadata["text"] for match in reference_result.matches)

        return {"table_matches": table_matches, "rag_snippet": rag_snippet}
    except Exception:
        return retrieve_context_keyword(direction, answers)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_retrieval.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add retrieval.py tests/test_retrieval.py
git commit -m "Add retrieval module: Pinecone-backed context with keyword fallback"
```

---

### Task 6: Pinecone ingestion script

**Files:**
- Create: `pinecone_ingest.py`
- Test: `tests/test_pinecone_ingest.py`

**Interfaces:**
- Consumes: `retrieval.DATA_DIR`, `retrieval.load_table`, `retrieval.extract_rag_section`,
  `retrieval.get_pinecone_index`, `llm_client.get_llm_client`, `llm_client.embed_text`.
- Produces: `pinecone_ingest.ingest_causes(index, embed_client) -> int` (rows ingested),
  `pinecone_ingest.ingest_reference(index, embed_client) -> int` (chunks ingested),
  `pinecone_ingest.main()` (script entry point).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pinecone_ingest.py
from unittest.mock import MagicMock

import pinecone_ingest


def test_ingest_causes_upserts_all_rows(monkeypatch):
    monkeypatch.setattr(pinecone_ingest, "embed_text", lambda client, text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(
        pinecone_ingest, "load_table",
        lambda: [
            {"state": "היפר", "category": "cat1", "cause": "cause1", "explanation": "exp1", "time_to_effect": "5m"},
            {"state": "היפו", "category": "cat2", "cause": "cause2", "explanation": "exp2", "time_to_effect": "10m"},
        ],
    )
    fake_index = MagicMock()

    count = pinecone_ingest.ingest_causes(fake_index, embed_client=object())

    assert count == 2
    fake_index.upsert.assert_called_once()
    kwargs = fake_index.upsert.call_args.kwargs
    assert kwargs["namespace"] == "causes"
    assert len(kwargs["vectors"]) == 2
    assert kwargs["vectors"][0]["metadata"]["state"] == "היפר"
    assert kwargs["vectors"][0]["values"] == [0.1, 0.2, 0.3]


def test_ingest_reference_upserts_chunks_with_direction_metadata(monkeypatch, tmp_path):
    ada_dir = tmp_path / "rag"
    ada_dir.mkdir()
    ada_file = ada_dir / "ada_diabetes_association.txt"
    ada_file.write_text("## HYPERGLYCEMIA\nhigh info\n## HYPOGLYCEMIA\nlow info", encoding="utf-8")
    niddk_file = ada_dir / "niddk_hypoglycemia.txt"
    niddk_file.write_text("niddk low info", encoding="utf-8")

    monkeypatch.setattr(pinecone_ingest, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pinecone_ingest, "embed_text", lambda client, text: [0.1, 0.2, 0.3])
    fake_index = MagicMock()

    count = pinecone_ingest.ingest_reference(fake_index, embed_client=object())

    assert count == 3  # high chunk, low chunk from ADA, low chunk from NIDDK
    kwargs = fake_index.upsert.call_args.kwargs
    assert kwargs["namespace"] == "reference"
    directions = {v["metadata"]["direction"] for v in kwargs["vectors"]}
    assert directions == {"high", "low"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pinecone_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pinecone_ingest'`

- [ ] **Step 3: Write `pinecone_ingest.py`**

```python
"""One-time script: embed investigation_table.json + RAG text chunks into
Pinecone. Run manually after LLMod.ai and Pinecone credentials are set in
.env:

    python pinecone_ingest.py

Re-run only when data/investigation_table.json or data/rag/*.txt change;
this is not part of the request-time path.
"""
from __future__ import annotations

from llm_client import embed_text, get_llm_client
from retrieval import DATA_DIR, extract_rag_section, get_pinecone_index, load_table


def ingest_causes(index, embed_client) -> int:
    rows = load_table()
    vectors = []
    for i, row in enumerate(rows):
        text = f"{row['category']} {row['cause']} {row['explanation']}"
        vector = embed_text(embed_client, text)
        vectors.append({
            "id": f"cause-{i}",
            "values": vector,
            "metadata": {
                "state": row["state"],
                "category": row["category"],
                "cause": row["cause"],
                "explanation": row["explanation"],
                "time_to_effect": row.get("time_to_effect", ""),
            },
        })
    index.upsert(vectors=vectors, namespace="causes")
    return len(vectors)


def ingest_reference(index, embed_client) -> int:
    ada_text = (DATA_DIR / "rag" / "ada_diabetes_association.txt").read_text(encoding="utf-8")
    niddk_text = (DATA_DIR / "rag" / "niddk_hypoglycemia.txt").read_text(encoding="utf-8")

    chunks = [
        ("high", extract_rag_section(ada_text, "high"), "ada_diabetes_association.txt"),
        ("low", extract_rag_section(ada_text, "low"), "ada_diabetes_association.txt"),
        ("low", niddk_text.strip(), "niddk_hypoglycemia.txt"),
    ]

    vectors = []
    for i, (direction, text, source_file) in enumerate(chunks):
        if not text:
            continue
        vector = embed_text(embed_client, text)
        vectors.append({
            "id": f"reference-{i}",
            "values": vector,
            "metadata": {"direction": direction, "source_file": source_file, "text": text},
        })
    index.upsert(vectors=vectors, namespace="reference")
    return len(vectors)


def main() -> None:
    embed_client = get_llm_client()
    index = get_pinecone_index()
    causes_count = ingest_causes(index, embed_client)
    reference_count = ingest_reference(index, embed_client)
    print(f"Ingested {causes_count} cause rows and {reference_count} reference chunks.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pinecone_ingest.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add pinecone_ingest.py tests/test_pinecone_ingest.py
git commit -m "Add one-time Pinecone ingestion script for causes + reference text"
```

---

### Task 7: Supabase audit log (non-blocking)

**Files:**
- Create: `supabase_log.py`
- Create: `supabase/migration.sql`
- Test: `tests/test_supabase_log.py`

**Interfaces:**
- Consumes: `config.require`, `config.SUPABASE_URL`, `config.SUPABASE_KEY`.
- Produces: `supabase_log.log_execution(prompt: str, response: str | None, steps: list[dict]) -> None`
  (never raises).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_supabase_log.py
import supabase_log


def test_log_execution_swallows_client_construction_errors(monkeypatch):
    def raise_error():
        raise RuntimeError("supabase down")

    monkeypatch.setattr(supabase_log, "_get_client", raise_error)

    supabase_log.log_execution("prompt", "response", [{"module": "x"}])  # must not raise


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

    supabase_log.log_execution("prompt text", "response text", [{"module": "CGM Event"}])

    assert calls["table_name"] == "execution_log"
    assert calls["payload"]["prompt"] == "prompt text"
    assert calls["payload"]["response"] == "response text"
    assert '"module": "CGM Event"' in calls["payload"]["steps"]
    assert calls["executed"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_supabase_log.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'supabase_log'`

- [ ] **Step 3: Write `supabase/migration.sql`**

```sql
create table if not exists execution_log (
    id bigint generated always as identity primary key,
    prompt text not null,
    response text,
    steps jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);
```

Run this once, manually, in your Supabase project's SQL Editor (Supabase dashboard → SQL Editor →
paste → Run). This is not something the test suite or application code can do for you.

- [ ] **Step 4: Write `supabase_log.py`**

```python
"""Non-blocking audit log of /api/execute calls. Logging failures must
never propagate to the caller — this is a side effect, not part of the
pipeline's contract.
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


def log_execution(prompt: str, response: str | None, steps: list[dict]) -> None:
    try:
        client = _get_client()
        client.table("execution_log").insert({
            "prompt": prompt,
            "response": response,
            "steps": json.dumps(steps, ensure_ascii=False),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        print(f"[supabase_log] failed to log execution (non-fatal): {e}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_supabase_log.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add supabase_log.py supabase/migration.sql tests/test_supabase_log.py
git commit -m "Add non-blocking Supabase audit log for /api/execute calls"
```

---

### Task 8: `agent_pipeline.py` part A — CGM event parsing

**Files:**
- Create: `agent_pipeline.py`
- Test: `tests/test_agent_pipeline_cgm_event.py`

**Interfaces:**
- Consumes: `llm_client.chat_json`, `errors.PipelineError`.
- Produces: `agent_pipeline.ALLOWED_TYPES`, `agent_pipeline.ALLOWED_SEVERITIES`,
  `agent_pipeline.parse_cgm_event(prompt: str, llm_client) -> tuple[dict, list[dict]]` (returns
  `(anomaly_dict, steps_so_far)` — `steps_so_far` is `[]` when the JSON shortcut was used, or a
  single `CGM Event` step when the LLM was called).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_pipeline_cgm_event.py
import json
from unittest.mock import MagicMock

import pytest

from agent_pipeline import parse_cgm_event
from errors import PipelineError


def _fake_llm_client(content: str):
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=content))
    ]
    return client


def test_json_shortcut_skips_llm_call():
    prompt = json.dumps({
        "type": "glucose_extreme", "severity": "urgent", "direction": "high",
        "message": "glucose at 260", "details": {"sgv": 260},
    })
    client = MagicMock()

    anomaly, steps = parse_cgm_event(prompt, client)

    assert anomaly["type"] == "glucose_extreme"
    assert anomaly["direction"] == "high"
    assert steps == []
    client.chat.completions.create.assert_not_called()


def test_json_shortcut_ignores_unrecognized_type():
    prompt = json.dumps({
        "type": "not_a_real_type", "severity": "urgent", "direction": "high",
        "message": "m", "details": {},
    })
    client = _fake_llm_client(json.dumps({
        "type": "glucose_extreme", "severity": "urgent", "direction": "high",
        "message": "m", "details": {},
    }))

    anomaly, steps = parse_cgm_event(prompt, client)

    assert len(steps) == 1  # fell through to the LLM path
    client.chat.completions.create.assert_called_once()


def test_free_text_calls_llm_and_returns_step():
    llm_response = json.dumps({
        "type": "rate_of_change", "severity": "warning", "direction": "low",
        "message": "falling fast", "details": {},
    })
    client = _fake_llm_client(llm_response)

    anomaly, steps = parse_cgm_event("my kid's sugar is dropping fast", client)

    assert anomaly["direction"] == "low"
    assert len(steps) == 1
    assert steps[0]["module"] == "CGM Event"


def test_rejects_non_cgm_description():
    client = _fake_llm_client(json.dumps({"error": "not a CGM event description"}))

    with pytest.raises(PipelineError, match="not a recognizable CGM event"):
        parse_cgm_event("what's the weather today?", client)


def test_big_gap_anomaly_allows_null_direction():
    prompt = json.dumps({
        "type": "big_gap", "severity": "urgent", "direction": None,
        "message": "no reading for 40 min", "details": {},
    })
    client = MagicMock()

    anomaly, steps = parse_cgm_event(prompt, client)

    assert anomaly["direction"] is None
    assert steps == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent_pipeline_cgm_event.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_pipeline'`

- [ ] **Step 3: Write `agent_pipeline.py` (part A)**

```python
"""Core reasoning pipeline: CGM event parsing, the bounded ReAct Agent,
Confidence Classification, Parent Summary, and the run_pipeline orchestrator
that ties them together across the multi-turn conversation.
"""
from __future__ import annotations
import json
import re

from errors import PipelineError
from llm_client import chat_json

ALLOWED_TYPES = {"rate_of_change", "big_gap", "iob_contextual", "glucose_extreme"}
ALLOWED_SEVERITIES = {"warning", "urgent"}
ALLOWED_DIRECTIONS = {"high", "low", None}

CGM_EVENT_SYSTEM_PROMPT = (
    "Extract a CGM (continuous glucose monitor) event from the user's description. "
    "Return ONLY JSON: {\"type\": str, \"severity\": str, \"direction\": str|null, "
    "\"message\": str, \"details\": object}. type must be one of "
    "[rate_of_change, big_gap, iob_contextual, glucose_extreme]. severity must be one "
    "of [warning, urgent]. direction must be 'high', 'low', or null. If the "
    "description does not describe a glucose event, return "
    "{\"error\": \"not a CGM event description\"}."
)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _valid_anomaly_dict(candidate) -> bool:
    return (
        isinstance(candidate, dict)
        and candidate.get("type") in ALLOWED_TYPES
        and candidate.get("severity") in ALLOWED_SEVERITIES
        and candidate.get("direction", None) in ALLOWED_DIRECTIONS
        and isinstance(candidate.get("message"), str)
        and isinstance(candidate.get("details", {}), dict)
    )


def _try_parse_json_shortcut(prompt: str) -> dict | None:
    match = _JSON_BLOCK.search(prompt)
    if not match:
        return None
    try:
        candidate = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not _valid_anomaly_dict(candidate):
        return None
    candidate.setdefault("details", {})
    return candidate


def parse_cgm_event(prompt: str, llm_client) -> tuple[dict, list[dict]]:
    shortcut = _try_parse_json_shortcut(prompt)
    if shortcut is not None:
        return shortcut, []

    parsed, step = chat_json(llm_client, "CGM Event", CGM_EVENT_SYSTEM_PROMPT, prompt)
    if parsed.get("error") or not _valid_anomaly_dict(parsed):
        raise PipelineError("not a recognizable CGM event description")
    parsed.setdefault("details", {})
    return parsed, [step]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent_pipeline_cgm_event.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add agent_pipeline.py tests/test_agent_pipeline_cgm_event.py
git commit -m "Add agent_pipeline.parse_cgm_event: JSON shortcut + LLM fallback"
```

---

### Task 9: `agent_pipeline.py` part B — bounded ReAct Agent

**Files:**
- Modify: `agent_pipeline.py`
- Test: `tests/test_agent_pipeline_react.py`

**Interfaces:**
- Consumes: `llm_client.chat_json` (via existing import in `agent_pipeline.py`).
- Produces: `agent_pipeline.run_react_agent(anomaly: dict, answers: dict, notes: str, context: dict,
  llm_client, followup: dict | None = None, allow_followup: bool = True) -> tuple[dict, dict]`
  — returns `({"need_more_info": bool, "followup_question": str | None, "findings": list | None},
  step)`. When `allow_followup=False` and the model still requests more info, the pipeline
  overrides it to `need_more_info=False, findings=[]` (or whatever findings were given).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_pipeline_react.py
import json
from unittest.mock import MagicMock

from agent_pipeline import run_react_agent

ANOMALY = {"type": "glucose_extreme", "severity": "urgent", "direction": "high", "message": "m", "details": {}}
ANSWERS = {"exercised_last_4h": True}
CONTEXT = {"table_matches": [], "rag_snippet": ""}


def _fake_llm_client(content: str):
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=content))
    ]
    return client


def test_requests_followup_when_more_info_needed():
    client = _fake_llm_client(json.dumps({
        "need_more_info": True, "followup_question": "מתי אכלת לאחרונה?", "findings": None,
    }))

    result, step = run_react_agent(ANOMALY, ANSWERS, "", CONTEXT, client)

    assert result["need_more_info"] is True
    assert result["followup_question"] == "מתי אכלת לאחרונה?"
    assert step["module"] == "ReAct Agent"


def test_finalizes_without_followup_when_confident():
    client = _fake_llm_client(json.dumps({
        "need_more_info": False, "followup_question": None,
        "findings": [{"cause": "exercise", "evidence": "answered yes", "source": "answers"}],
    }))

    result, step = run_react_agent(ANOMALY, ANSWERS, "", CONTEXT, client)

    assert result["need_more_info"] is False
    assert result["findings"][0]["cause"] == "exercise"


def test_forced_final_call_uses_followup_suffix_in_prompt():
    client = _fake_llm_client(json.dumps({
        "need_more_info": False, "followup_question": None, "findings": [],
    }))

    run_react_agent(
        ANOMALY, ANSWERS, "", CONTEXT, client,
        followup={"question": "q?", "answer": "a"}, allow_followup=False,
    )

    system_prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "no further follow-up is allowed" in system_prompt


def test_forced_final_ignores_disobedient_followup_request():
    client = _fake_llm_client(json.dumps({
        "need_more_info": True, "followup_question": "one more?", "findings": None,
    }))

    result, step = run_react_agent(ANOMALY, ANSWERS, "", CONTEXT, client, allow_followup=False)

    assert result["need_more_info"] is False
    assert result["findings"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent_pipeline_react.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_react_agent' from 'agent_pipeline'`

- [ ] **Step 3: Append to `agent_pipeline.py`**

```python
REACT_SYSTEM_PROMPT_BASE = (
    "You are a diabetes event investigation assistant for a parent-teen pair. Given a "
    "CGM anomaly, structured yes/no answers with free-text notes, retrieved "
    "candidate-cause table rows, and medical reference text, reason step by step. If "
    "one additional piece of information from the teen would meaningfully change your "
    "findings, return ONLY JSON: {\"need_more_info\": true, \"followup_question\": "
    "\"<your question, in Hebrew>\", \"findings\": null}. Otherwise return ONLY JSON: "
    "{\"need_more_info\": false, \"followup_question\": null, \"findings\": "
    "[{\"cause\": str, \"evidence\": str, \"source\": \"table\"|\"reference\"|\"answers\"}]}. "
    "List up to 3 findings ordered by plausibility. Do not diagnose or invent facts not "
    "supported by the given context."
)

REACT_FORCED_FINAL_SUFFIX = (
    " You must set need_more_info to false and provide findings now — no further "
    "follow-up is allowed."
)


def _build_react_user_prompt(anomaly, answers, notes, context, followup=None) -> str:
    payload = {
        "anomaly": anomaly,
        "questionnaire_answers": answers,
        "notes": notes,
        "candidate_causes": context["table_matches"],
        "reference_text": context["rag_snippet"],
    }
    if followup:
        payload["followup_question"] = followup["question"]
        payload["followup_answer"] = followup["answer"]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def run_react_agent(
    anomaly, answers, notes, context, llm_client, followup=None, allow_followup=True
) -> tuple[dict, dict]:
    system_prompt = REACT_SYSTEM_PROMPT_BASE
    if not allow_followup:
        system_prompt += REACT_FORCED_FINAL_SUFFIX

    user_prompt = _build_react_user_prompt(anomaly, answers, notes, context, followup)
    parsed, step = chat_json(llm_client, "ReAct Agent", system_prompt, user_prompt)

    if not allow_followup and parsed.get("need_more_info"):
        parsed = {
            "need_more_info": False,
            "followup_question": None,
            "findings": parsed.get("findings") or [],
        }

    return parsed, step
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent_pipeline_react.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agent_pipeline.py tests/test_agent_pipeline_react.py
git commit -m "Add agent_pipeline.run_react_agent: bounded 0-or-1 follow-up loop"
```

---

### Task 10: `agent_pipeline.py` part C — Confidence Classification + Parent Summary

**Files:**
- Modify: `agent_pipeline.py`
- Test: `tests/test_agent_pipeline_finalize.py`

**Interfaces:**
- Consumes: `llm_client.chat_json` (existing import).
- Produces:
  `agent_pipeline.run_confidence_classification(anomaly: dict, answers: dict, findings: list, llm_client) -> tuple[dict, dict]`
  (returns `({"findings": [...with confidence + rationale...]}, step)`),
  `agent_pipeline.run_parent_summary(anomaly: dict, answers: dict, findings: list, llm_client) -> tuple[dict, dict]`
  (returns `({"parent_summary": str}, step)`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_pipeline_finalize.py
import json
from unittest.mock import MagicMock

from agent_pipeline import run_confidence_classification, run_parent_summary

ANOMALY = {"type": "glucose_extreme", "severity": "urgent", "direction": "high", "message": "m", "details": {}}
ANSWERS = {"exercised_last_4h": True}
FINDINGS = [{"cause": "exercise", "evidence": "answered yes", "source": "answers"}]


def _fake_llm_client(content: str):
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=content))
    ]
    return client


def test_run_confidence_classification_adds_confidence_and_rationale():
    client = _fake_llm_client(json.dumps({
        "findings": [{"cause": "exercise", "evidence": "answered yes",
                      "confidence": "medium", "rationale": "plausible but not confirmed"}],
    }))

    result, step = run_confidence_classification(ANOMALY, ANSWERS, FINDINGS, client)

    assert result["findings"][0]["confidence"] == "medium"
    assert step["module"] == "Confidence Classification"


def test_run_confidence_classification_prompt_excludes_raw_context():
    client = _fake_llm_client(json.dumps({"findings": []}))

    run_confidence_classification(ANOMALY, ANSWERS, FINDINGS, client)

    user_prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "candidate_causes" not in user_prompt
    assert "reference_text" not in user_prompt


def test_run_parent_summary_returns_summary_text():
    client = _fake_llm_client(json.dumps({
        "parent_summary": "Event recap. Possible reason: exercise (medium confidence). Suggestion: hydrate.",
    }))
    scored_findings = [{"cause": "exercise", "evidence": "e", "confidence": "medium", "rationale": "r"}]

    result, step = run_parent_summary(ANOMALY, ANSWERS, scored_findings, client)

    assert result["parent_summary"].startswith("Event recap.")
    assert step["module"] == "Parent Summary"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent_pipeline_finalize.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_confidence_classification' from 'agent_pipeline'`

- [ ] **Step 3: Append to `agent_pipeline.py`**

```python
CONFIDENCE_SYSTEM_PROMPT = (
    "You score confidence for each candidate finding about what caused a glucose "
    "anomaly. Given the anomaly, questionnaire answers, and a list of candidate "
    "findings with their supporting evidence, return ONLY JSON: {\"findings\": "
    "[{\"cause\": str, \"evidence\": str, \"confidence\": \"low\"|\"medium\"|\"high\", "
    "\"rationale\": str}]}, preserving each finding's cause/evidence and adding "
    "confidence and a one-sentence rationale. Base confidence on how directly the "
    "evidence supports each cause."
)

PARENT_SUMMARY_SYSTEM_PROMPT = (
    "You write a parent-facing summary of a glucose anomaly investigation. Given the "
    "anomaly, the teen's questionnaire answers, and confidence-scored candidate "
    "findings, return ONLY JSON: {\"parent_summary\": str}. parent_summary must read "
    "as: a 2-3 sentence recap of the event and what the teen reported, then up to "
    "three possible reasons ordered by confidence (each stated with its confidence "
    "level), then one practical suggestion. Do not diagnose; present reasons as "
    "possibilities, not conclusions."
)


def run_confidence_classification(anomaly, answers, findings, llm_client) -> tuple[dict, dict]:
    user_prompt = json.dumps(
        {"anomaly": anomaly, "questionnaire_answers": answers, "findings": findings},
        ensure_ascii=False, indent=2,
    )
    return chat_json(llm_client, "Confidence Classification", CONFIDENCE_SYSTEM_PROMPT, user_prompt)


def run_parent_summary(anomaly, answers, findings, llm_client) -> tuple[dict, dict]:
    user_prompt = json.dumps(
        {"anomaly": anomaly, "questionnaire_answers": answers, "findings": findings},
        ensure_ascii=False, indent=2,
    )
    return chat_json(llm_client, "Parent Summary", PARENT_SUMMARY_SYSTEM_PROMPT, user_prompt)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent_pipeline_finalize.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agent_pipeline.py tests/test_agent_pipeline_finalize.py
git commit -m "Add agent_pipeline Confidence Classification + Parent Summary stages"
```

---

### Task 11: `agent_pipeline.py` part D — `run_pipeline` orchestrator

**Files:**
- Modify: `agent_pipeline.py`
- Test: `tests/test_agent_pipeline_run_pipeline.py`

**Interfaces:**
- Consumes: `conversation_state.extract_conversation_state`, `conversation_state.build_marker`,
  `questionnaire.format_questionnaire_prompt`, `questionnaire.parse_answers`,
  `retrieval.retrieve_context_keyword`, `retrieval.retrieve_context_pinecone`, plus all of
  `agent_pipeline`'s own functions from Tasks 8–10.
- Produces: `agent_pipeline.PipelineClients` dataclass (`llm_client`, `pinecone_index=None`,
  `embed_client=None`), `agent_pipeline.run_pipeline(prompt: str, clients: PipelineClients) ->
  dict` (returns `{"response": str, "steps": list[dict]}` — this is the exact shape the future
  `/api/execute` handler returns before the FastAPI layer adds `status`/`error`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_pipeline_run_pipeline.py
import json
from unittest.mock import MagicMock

import agent_pipeline
from agent_pipeline import PipelineClients, run_pipeline
from conversation_state import build_marker

ANOMALY = {"type": "glucose_extreme", "severity": "urgent", "direction": "high", "message": "m", "details": {}}
ALL_TEN_ANSWERS = {
    "ate_recently": True, "carb_count_accurate": True, "exercised_last_4h": True,
    "stressed_last_30min": False, "drank_water_today": True, "hot_weather_last_30min": False,
    "correction_dose_last_3h": False, "phone_sensor_check_last_hour": True,
    "accurate_meals_today": True, "finger_stick_or_calibration_recent": False,
}


def _client_with_responses(*json_contents):
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content=c))]) for c in json_contents
    ]
    return client


def _ten_answers_reply() -> str:
    return "\n".join(f"{i}. Y" for i in range(1, 11))


def test_turn1_fresh_prompt_returns_questionnaire():
    client = _client_with_responses()  # JSON shortcut expected; no LLM call
    prompt = json.dumps(ANOMALY)
    clients = PipelineClients(llm_client=client)

    result = run_pipeline(prompt, clients)

    assert "SUGARBUDDY_CONTEXT" in result["response"]
    assert "1." in result["response"] and "10." in result["response"]
    assert result["steps"] == []


def test_turn2_no_followup_returns_final_summary(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline, "retrieve_context_keyword",
        lambda direction, answers: {"table_matches": [], "rag_snippet": ""},
    )
    react_response = json.dumps({
        "need_more_info": False, "followup_question": None,
        "findings": [{"cause": "exercise", "evidence": "e", "source": "answers"}],
    })
    confidence_response = json.dumps({
        "findings": [{"cause": "exercise", "evidence": "e", "confidence": "medium", "rationale": "r"}],
    })
    summary_response = json.dumps({
        "parent_summary": "Event recap. Possible reason: exercise (medium confidence). Suggestion: hydrate.",
    })
    client = _client_with_responses(react_response, confidence_response, summary_response)
    clients = PipelineClients(llm_client=client)

    marker = build_marker("questionnaire_sent", anomaly=ANOMALY)
    prompt = f"{marker}\n{_ten_answers_reply()}"

    result = run_pipeline(prompt, clients)

    assert result["response"] == "Event recap. Possible reason: exercise (medium confidence). Suggestion: hydrate."
    assert [s["module"] for s in result["steps"]] == [
        "ReAct Agent", "Confidence Classification", "Parent Summary",
    ]


def test_turn2_with_followup_returns_question_not_summary(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline, "retrieve_context_keyword",
        lambda direction, answers: {"table_matches": [], "rag_snippet": ""},
    )
    react_response = json.dumps({
        "need_more_info": True, "followup_question": "כמה זמן אחרי האוכל מדדת?", "findings": None,
    })
    client = _client_with_responses(react_response)
    clients = PipelineClients(llm_client=client)

    marker = build_marker("questionnaire_sent", anomaly=ANOMALY)
    prompt = f"{marker}\n{_ten_answers_reply()}"

    result = run_pipeline(prompt, clients)

    assert "כמה זמן אחרי האוכל מדדת?" in result["response"]
    assert "followup_sent" in result["response"]
    assert [s["module"] for s in result["steps"]] == ["ReAct Agent"]


def test_turn3_after_followup_returns_final_summary(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline, "retrieve_context_keyword",
        lambda direction, answers: {"table_matches": [], "rag_snippet": ""},
    )
    react_response = json.dumps({
        "need_more_info": False, "followup_question": None,
        "findings": [{"cause": "late meal", "evidence": "e", "source": "answers"}],
    })
    confidence_response = json.dumps({
        "findings": [{"cause": "late meal", "evidence": "e", "confidence": "high", "rationale": "r"}],
    })
    summary_response = json.dumps({"parent_summary": "Final summary text."})
    client = _client_with_responses(react_response, confidence_response, summary_response)
    clients = PipelineClients(llm_client=client)

    marker = build_marker(
        "followup_sent", anomaly=ANOMALY, answers=ALL_TEN_ANSWERS, notes="",
        followup_question="כמה זמן אחרי האוכל מדדת?",
    )
    prompt = f"{marker}\nכעשר דקות אחרי"

    result = run_pipeline(prompt, clients)

    assert result["response"] == "Final summary text."
    assert [s["module"] for s in result["steps"]] == [
        "ReAct Agent", "Confidence Classification", "Parent Summary",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent_pipeline_run_pipeline.py -v`
Expected: FAIL with `ImportError: cannot import name 'PipelineClients' from 'agent_pipeline'`

- [ ] **Step 3: Append to `agent_pipeline.py`**

```python
from dataclasses import dataclass

from conversation_state import build_marker, extract_conversation_state
from questionnaire import format_questionnaire_prompt, parse_answers
from retrieval import retrieve_context_keyword, retrieve_context_pinecone


@dataclass
class PipelineClients:
    llm_client: object
    pinecone_index: object = None
    embed_client: object = None


def _retrieve_context(anomaly: dict, answers: dict, clients: PipelineClients) -> dict:
    direction = anomaly.get("direction")
    if clients.pinecone_index is not None and clients.embed_client is not None:
        return retrieve_context_pinecone(direction, answers, clients.embed_client, clients.pinecone_index)
    return retrieve_context_keyword(direction, answers)


def _finalize(anomaly, answers, findings, clients: PipelineClients, prior_steps: list[dict]) -> dict:
    confidence_result, confidence_step = run_confidence_classification(
        anomaly, answers, findings, clients.llm_client
    )
    summary_result, summary_step = run_parent_summary(
        anomaly, answers, confidence_result["findings"], clients.llm_client
    )
    return {
        "response": summary_result["parent_summary"],
        "steps": prior_steps + [confidence_step, summary_step],
    }


def run_pipeline(prompt: str, clients: PipelineClients) -> dict:
    state = extract_conversation_state(prompt)

    if state is None or state.stage not in ("questionnaire_sent", "followup_sent"):
        anomaly, steps = parse_cgm_event(prompt, clients.llm_client)
        return {"response": format_questionnaire_prompt(anomaly), "steps": steps}

    if state.stage == "questionnaire_sent":
        answers, notes = parse_answers(state.reply_text)
        context = _retrieve_context(state.anomaly, answers, clients)
        result, react_step = run_react_agent(state.anomaly, answers, notes, context, clients.llm_client)

        if result.get("need_more_info"):
            marker = build_marker(
                "followup_sent", anomaly=state.anomaly, answers=answers, notes=notes,
                followup_question=result["followup_question"],
            )
            return {"response": f"{result['followup_question']}\n\n{marker}", "steps": [react_step]}

        return _finalize(state.anomaly, answers, result["findings"], clients, [react_step])

    # state.stage == "followup_sent"
    followup_answer = state.reply_text
    context = _retrieve_context(state.anomaly, state.answers, clients)
    result, react_step = run_react_agent(
        state.anomaly, state.answers, state.notes, context, clients.llm_client,
        followup={"question": state.followup_question, "answer": followup_answer},
        allow_followup=False,
    )
    return _finalize(state.anomaly, state.answers, result["findings"], clients, [react_step])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent_pipeline_run_pipeline.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full automated test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS (all tests across all tasks — roughly 47 tests)

- [ ] **Step 6: Commit**

```bash
git add agent_pipeline.py tests/test_agent_pipeline_run_pipeline.py
git commit -m "Add agent_pipeline.run_pipeline: dispatches turn 1/2/3 conversation flow"
```

---

### Task 12: Rewrite `local_prototype.py` as the interactive manual smoke test

**Files:**
- Modify: `local_prototype.py` (full rewrite — the old stub-based flow is superseded by
  `agent_pipeline.run_pipeline`)

**Interfaces:**
- Consumes: `agent_pipeline.PipelineClients`, `agent_pipeline.run_pipeline`,
  `llm_client.get_llm_client`, `retrieval.get_pinecone_index_safe`.
- Produces: a `main()` entry point for manual, interactive testing. No automated test — this
  makes real LLM/embedding/Pinecone calls and is meant to be run by a developer with real
  credentials configured.

- [ ] **Step 1: Rewrite `local_prototype.py`**

```python
"""Interactive end-to-end smoke test for the SugarBuddy agent pipeline.

Run manually once LLMOD_API_KEY / LLMOD_BASE_URL are set in .env (and,
optionally, PINECONE_API_KEY for Pinecone-backed retrieval instead of the
keyword fallback):

    python local_prototype.py

Drives the full multi-turn flow via input(): describe a CGM event, answer
the 10 questions, optionally answer one follow-up question, and read the
final parent summary. This is a manual verification tool, not part of the
automated test suite (see tests/) — it makes real network calls.
"""
from __future__ import annotations
import json

from agent_pipeline import PipelineClients, run_pipeline
from llm_client import get_llm_client
from retrieval import get_pinecone_index_safe


def main() -> None:
    llm_client = get_llm_client()
    pinecone_index = get_pinecone_index_safe()
    if pinecone_index is None:
        print("[info] Pinecone not configured — falling back to keyword-matching retrieval.\n")

    clients = PipelineClients(llm_client=llm_client, pinecone_index=pinecone_index, embed_client=llm_client)

    print("Describe the CGM event (e.g. 'glucose spiked to 260 mg/dL and is rising fast'):")
    transcript = input("> ").strip()

    while True:
        result = run_pipeline(transcript, clients)

        print("\n=== Agent response ===")
        print(result["response"])
        print("\n=== Steps ===")
        print(json.dumps(result["steps"], ensure_ascii=False, indent=2))

        if "SUGARBUDDY_CONTEXT" not in result["response"]:
            print("\n=== Done: final parent summary reached ===")
            break

        print("\nYour reply (questionnaire answers or the follow-up answer):")
        reply = input("> ").strip()
        transcript = f"{transcript}\n{result['response']}\n{reply}"


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual verification run (requires real credentials in `.env`)**

Run: `python local_prototype.py`

Try at least two scenarios end-to-end:
1. A scenario worded so the ReAct Agent should have enough from the 10 answers alone (no
   follow-up) — confirm you get a final parent summary with an event recap, up to 3 reasons with
   confidence levels, and one suggestion, after exactly one round of questions.
2. A scenario worded ambiguously enough that the ReAct Agent asks its one follow-up question —
   confirm you're prompted for it, and that answering it produces the final summary.

Confirm in both cases that the printed `steps` array uses the module names `CGM Event` (if it
appeared), `ReAct Agent`, `Confidence Classification`, `Parent Summary` — nothing else.

- [ ] **Step 3: Commit**

```bash
git add local_prototype.py
git commit -m "Rewrite local_prototype.py as interactive smoke test for the real pipeline"
```

---

## After this plan

Per the spec's scope section, still needed (separate follow-on plans): the FastAPI app and its
four required endpoints (wrapping `agent_pipeline.run_pipeline` and `supabase_log.log_execution`),
the `/api/model_architecture` PNG export, the GUI (including the parent-decision-to-teen relay,
which is a plain-text pass-through with no pipeline involvement), and Vercel deployment.
