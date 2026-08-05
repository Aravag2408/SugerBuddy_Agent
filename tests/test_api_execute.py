# tests/test_api_execute.py
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import api.index as api_index
from api.index import app
from errors import PipelineError

client = TestClient(app)


def test_execute_success_returns_ok_shape(monkeypatch):
    fake_result = {
        "response": "some response text",
        "steps": [{"module": "CGM Event", "prompt": {"system_prompt": "s", "user_prompt": "u"}, "response": {}}],
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
