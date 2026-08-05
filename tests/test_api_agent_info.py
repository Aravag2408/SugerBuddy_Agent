# tests/test_api_agent_info.py
from fastapi.testclient import TestClient

from agent_pipeline import REACT_SYSTEM_PROMPT_BASE
from api.index import app

client = TestClient(app)

REQUIRED_KEYS = {"description", "purpose", "prompt_template", "prompt_examples"}
EXPECTED_MODULES = ["CGM Event", "ReAct Agent", "Confidence Classification", "Parent Summary"]


def test_agent_info_has_required_top_level_keys():
    response = client.get("/api/agent_info")

    assert response.status_code == 200
    body = response.json()
    assert REQUIRED_KEYS.issubset(body.keys())
    assert "template" in body["prompt_template"]


def test_agent_info_prompt_examples_are_well_formed():
    response = client.get("/api/agent_info")
    body = response.json()

    assert len(body["prompt_examples"]) == 2
    for example in body["prompt_examples"]:
        assert isinstance(example["prompt"], str) and example["prompt"]
        assert isinstance(example["full_response"], str) and example["full_response"]
        modules = [s["module"] for s in example["steps"]]
        assert modules == EXPECTED_MODULES


def test_agent_info_system_prompts_match_live_agent_pipeline_constants():
    response = client.get("/api/agent_info")
    body = response.json()

    react_step = body["prompt_examples"][0]["steps"][1]
    assert react_step["module"] == "ReAct Agent"
    assert react_step["prompt"]["system_prompt"] == REACT_SYSTEM_PROMPT_BASE
