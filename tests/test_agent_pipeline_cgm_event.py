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
