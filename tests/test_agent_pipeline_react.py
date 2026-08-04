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
    assert result["followup_question"] is None
    assert result["findings"] == []
