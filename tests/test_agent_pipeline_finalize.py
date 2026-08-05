import json
from unittest.mock import MagicMock

import pytest

from agent_pipeline import (
    CONFIDENCE_SYSTEM_PROMPT,
    PARENT_SUMMARY_SYSTEM_PROMPT,
    REACT_SYSTEM_PROMPT_BASE,
    run_confidence_classification,
    run_parent_summary,
)

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
    prompt_dict = json.loads(user_prompt)
    # Positive exhaustive check: prompt contains exactly these top-level keys and no others
    assert set(prompt_dict.keys()) == {"anomaly", "questionnaire_answers", "findings"}


def test_run_parent_summary_returns_summary_text():
    client = _fake_llm_client(json.dumps({
        "parent_summary": "Event recap. Possible reason: exercise (medium confidence). Suggestion: hydrate.",
    }))
    scored_findings = [{"cause": "exercise", "evidence": "e", "confidence": "medium", "rationale": "r"}]

    result, step = run_parent_summary(ANOMALY, ANSWERS, scored_findings, client)

    assert result["parent_summary"].startswith("Event recap.")
    assert step["module"] == "Parent Summary"


@pytest.mark.parametrize(
    "system_prompt",
    [REACT_SYSTEM_PROMPT_BASE, CONFIDENCE_SYSTEM_PROMPT, PARENT_SUMMARY_SYSTEM_PROMPT],
    ids=["react", "confidence", "parent_summary"],
)
def test_every_user_facing_system_prompt_specifies_hebrew(system_prompt):
    """Every stage that emits text a Hebrew-speaking teen or parent will read must
    say so — parent_summary in particular is the whole user-visible deliverable."""
    assert "Hebrew" in system_prompt
