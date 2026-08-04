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
