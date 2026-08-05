import json
from unittest.mock import MagicMock

import agent_pipeline
from agent_pipeline import PipelineClients, run_pipeline
from conversation_state import build_marker, extract_conversation_state

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
    assert [s["module"] for s in result["steps"]] == ["ReAct Agent"]

    # conversation_state.build_marker base64-encodes its payload (fixed during
    # Task 2's review), so verify the embedded stage via a real round-trip
    # rather than checking for literal marker text in the response.
    followup_state = extract_conversation_state(result["response"])
    assert followup_state is not None
    assert followup_state.stage == "followup_sent"


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
