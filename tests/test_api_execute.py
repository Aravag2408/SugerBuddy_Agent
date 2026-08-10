# tests/test_api_execute.py
import json
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import api.index as api_index
from agent_pipeline import PipelineClients
from api.index import app
from errors import PipelineError

client = TestClient(app)


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


def test_execute_pipeline_error_returns_error_shape(monkeypatch):
    def raise_pipeline_error(prompt, clients):
        raise PipelineError("could not parse all questionnaire answers; reply as a numbered Y/N list")

    monkeypatch.setattr(api_index, "_get_clients", lambda: MagicMock())
    monkeypatch.setattr(api_index, "run_pipeline", raise_pipeline_error)

    response = client.post("/api/execute", json={"prompt": "1. Y"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "numbered Y/N list" in body["error"]
    assert body["response"] is None
    assert body["steps"] == []


def test_execute_unexpected_exception_returns_error_shape(monkeypatch):
    def raise_value_error(prompt, clients):
        raise ValueError("something unrelated broke")

    monkeypatch.setattr(api_index, "_get_clients", lambda: MagicMock())
    monkeypatch.setattr(api_index, "run_pipeline", raise_value_error)

    response = client.post("/api/execute", json={"prompt": "test"})

    body = response.json()
    assert body["status"] == "error"
    assert "something unrelated broke" in body["error"]
    assert body["response"] is None
    assert body["steps"] == []


def test_execute_missing_prompt_returns_error_shape():
    response = client.post("/api/execute", json={})

    body = response.json()
    assert body == {
        "status": "error",
        "error": "prompt is required",
        "response": None,
        "steps": [],
    }


def test_execute_non_string_prompt_returns_error_shape():
    response = client.post("/api/execute", json={"prompt": 12345})

    body = response.json()
    assert body["status"] == "error"
    assert body["error"] == "prompt is required"


def test_execute_no_body_returns_error_shape_not_500():
    response = client.post("/api/execute")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "error",
        "error": "prompt is required",
        "response": None,
        "steps": [],
    }


def test_execute_malformed_json_body_returns_error_shape_not_500():
    response = client.post(
        "/api/execute",
        content="not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "error",
        "error": "prompt is required",
        "response": None,
        "steps": [],
    }


def test_execute_overlong_prompt_rejected_before_any_client_or_pipeline_work(monkeypatch):
    """The endpoint is public and unauthenticated but LLM-backed, so an oversized
    prompt must be rejected in the handler -- never reaching _get_clients() or
    run_pipeline(), and so never costing an LLM call."""

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("overlong prompt reached the pipeline")

    monkeypatch.setattr(api_index, "_get_clients", must_not_be_called)
    monkeypatch.setattr(api_index, "run_pipeline", must_not_be_called)
    monkeypatch.setattr(api_index, "log_execution", must_not_be_called)

    response = client.post("/api/execute", json={"prompt": "x" * (api_index.MAX_PROMPT_CHARS + 1)})

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "error": "prompt is too long",
        "response": None,
        "steps": [],
    }


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


# --- Real seam: api.index <-> agent_pipeline, with only the LLM client faked ---


def _fake_llm_client(*json_contents):
    """A stand-in for the LLMod.ai client: same shape run_pipeline consumes
    (client.chat.completions.create -> .choices[0].message.content), fed canned
    JSON bodies in call order. No network, no LLM spend."""
    fake = MagicMock()
    fake.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content=c))]) for c in json_contents
    ]
    return fake


def test_two_real_execute_calls_run_the_real_pipeline_end_to_end(monkeypatch):
    """The one test that does NOT mock run_pipeline.

    Only _get_clients is replaced -- with a PipelineClients built exactly the way
    the real one is, but around a fake llm_client and with pinecone_index/embed_client
    left at None so the real keyword-fallback retrieval path (real data files) runs.
    Everything else is production code: real parse_cgm_event, real questionnaire
    formatting/parsing, real marker round-trip through two real HTTP POSTs, real
    ReAct/Confidence/Parent Summary orchestration.
    """
    anomaly_response = json.dumps({
        "type": "glucose_extreme", "severity": "urgent", "direction": "high",
        "message": "Glucose rose to 260 and is climbing fast.",
        "details": {"glucose": 260, "trend": "rising fast"},
    })
    react_response = json.dumps({
        "need_more_info": False, "followup_question": None,
        "findings": [{"cause": "עודף פחמימות", "evidence": "אכלה לאחרונה", "source": "table"}],
    })
    confidence_response = json.dumps({
        "findings": [{
            "cause": "עודף פחמימות", "evidence": "אכלה לאחרונה",
            "confidence": "medium", "rationale": "התאמה סבירה",
        }],
    })
    summary_response = json.dumps({"parent_summary": "סיכום סופי להורה."})

    fake_llm = _fake_llm_client(
        anomaly_response, react_response, confidence_response, summary_response
    )
    clients = PipelineClients(llm_client=fake_llm, pinecone_index=None, embed_client=None)

    monkeypatch.setattr(api_index, "_get_clients", lambda: clients)
    logged = []
    monkeypatch.setattr(api_index, "log_execution", lambda *a, **kw: logged.append(a))

    # --- Turn 1: free text describing the event -> the 10-question check-in ---
    turn1_prompt = "הסוכר קפץ ל-260 ועולה מהר"
    turn1 = client.post("/api/execute", json={"prompt": turn1_prompt}).json()

    assert turn1["status"] == "ok"
    assert turn1["error"] is None
    assert [s["module"] for s in turn1["steps"]] == ["CGM Event"]
    assert "10." in turn1["response"]
    # The state marker must ride back out to the client in the response text.
    assert "SUGARBUDDY_CONTEXT" in turn1["response"]

    # --- Turn 2: the accumulated transcript (marker included) + the 10 answers ---
    answers = "\n".join(f"{i}. Y" for i in range(1, 11))
    turn2_prompt = f"{turn1_prompt}\n{turn1['response']}\n{answers}"
    turn2 = client.post("/api/execute", json={"prompt": turn2_prompt}).json()

    assert turn2["status"] == "ok"
    assert turn2["error"] is None
    assert turn2["response"] == "סיכום סופי להורה."
    assert "SUGARBUDDY_CONTEXT" not in turn2["response"]
    assert [s["module"] for s in turn2["steps"]] == [
        "ReAct Agent", "Confidence Classification", "Parent Summary",
    ]
    for step in turn2["steps"]:
        assert step["prompt"]["system_prompt"] and step["prompt"]["user_prompt"]

    # The marker really round-tripped: the ReAct call saw the anomaly and the
    # parsed answers recovered from turn 1's marker, plus real retrieved context.
    react_payload = json.loads(
        fake_llm.chat.completions.create.call_args_list[1].kwargs["messages"][1]["content"]
    )
    assert react_payload["anomaly"]["direction"] == "high"
    assert react_payload["questionnaire_answers"]["ate_recently"] is True
    assert len(react_payload["questionnaire_answers"]) == 10
    # pinecone_index/embed_client were None, so the real keyword fallback ran
    # against the real data files and returned real reference text.
    assert react_payload["reference_text"]

    assert len(logged) == 2  # both turns were handed to the audit log
    assert logged[0][3]["stage"] == "initial"
    assert logged[0][3]["anomaly"]["direction"] == "high"
    assert logged[1][3]["stage"] == "questionnaire_sent"
    assert logged[1][3]["need_more_info"] is False
    assert logged[1][3]["parent_summary"] == "סיכום סופי להורה."
    assert logged[1][3]["retrieved_context"]["rag_snippet"]


def test_clients_are_built_lazily_and_never_at_import_time(monkeypatch):
    """_get_clients() must be the only thing that constructs credentials-backed
    clients, and it must not run until /api/execute actually needs them --
    otherwise importing api.index (which every endpoint depends on) would require
    live LLMod.ai/Pinecone config."""
    calls = []
    monkeypatch.setattr(api_index, "get_llm_client", lambda: calls.append("llm") or "LLM")
    monkeypatch.setattr(
        api_index, "get_pinecone_index_safe", lambda: calls.append("pinecone") or "INDEX"
    )
    # Other tests in this session may already have populated the cache.
    monkeypatch.setattr(api_index, "_clients", None)

    # Importing the module and serving the non-execute endpoints must not touch them.
    assert client.get("/api/team_info").status_code == 200
    assert client.get("/api/agent_info").status_code == 200
    assert client.get("/").status_code == 200
    assert calls == []

    built = api_index._get_clients()

    assert calls == ["llm", "pinecone"]
    assert isinstance(built, PipelineClients)
    assert built.llm_client == "LLM"
    assert built.pinecone_index == "INDEX"
    assert built.embed_client == "LLM"  # one client serves both chat and embeddings

    # ...and the result is cached, not rebuilt per request.
    assert api_index._get_clients() is built
    assert calls == ["llm", "pinecone"]
