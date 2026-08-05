import json
from unittest.mock import MagicMock

import pytest

import agent_pipeline
from agent_pipeline import PipelineClients, run_pipeline
from conversation_state import build_marker, extract_conversation_state
from errors import PipelineError

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


def test_turn2_uses_pinecone_when_both_clients_are_set(monkeypatch):
    pinecone_mock = MagicMock(return_value={"table_matches": [], "rag_snippet": ""})
    keyword_mock = MagicMock(side_effect=AssertionError("keyword fallback should not be used"))
    monkeypatch.setattr(agent_pipeline, "retrieve_context_pinecone", pinecone_mock)
    monkeypatch.setattr(agent_pipeline, "retrieve_context_keyword", keyword_mock)

    react_response = json.dumps({
        "need_more_info": False, "followup_question": None,
        "findings": [{"cause": "exercise", "evidence": "e", "source": "answers"}],
    })
    confidence_response = json.dumps({
        "findings": [{"cause": "exercise", "evidence": "e", "confidence": "medium", "rationale": "r"}],
    })
    summary_response = json.dumps({"parent_summary": "Summary via pinecone path."})
    client = _client_with_responses(react_response, confidence_response, summary_response)

    fake_pinecone_index = MagicMock(name="pinecone_index")
    fake_embed_client = MagicMock(name="embed_client")
    clients = PipelineClients(
        llm_client=client, pinecone_index=fake_pinecone_index, embed_client=fake_embed_client,
    )

    marker = build_marker("questionnaire_sent", anomaly=ANOMALY)
    prompt = f"{marker}\n{_ten_answers_reply()}"

    result = run_pipeline(prompt, clients)

    assert pinecone_mock.called
    assert pinecone_mock.call_args.args[2:] == (fake_embed_client, fake_pinecone_index)
    assert not keyword_mock.called
    assert result["response"] == "Summary via pinecone path."


def test_turn2_falls_back_to_keyword_when_only_one_client_is_set(monkeypatch):
    pinecone_mock = MagicMock(
        side_effect=AssertionError("pinecone should not be used when embed_client is None")
    )
    keyword_mock = MagicMock(return_value={"table_matches": [], "rag_snippet": ""})
    monkeypatch.setattr(agent_pipeline, "retrieve_context_pinecone", pinecone_mock)
    monkeypatch.setattr(agent_pipeline, "retrieve_context_keyword", keyword_mock)

    react_response = json.dumps({
        "need_more_info": False, "followup_question": None,
        "findings": [{"cause": "exercise", "evidence": "e", "source": "answers"}],
    })
    confidence_response = json.dumps({
        "findings": [{"cause": "exercise", "evidence": "e", "confidence": "medium", "rationale": "r"}],
    })
    summary_response = json.dumps({"parent_summary": "Summary via keyword fallback."})
    client = _client_with_responses(react_response, confidence_response, summary_response)

    # pinecone_index is set but embed_client is left at its None default — dispatch
    # must require BOTH to be set, not just one, before using the Pinecone path.
    fake_pinecone_index = MagicMock(name="pinecone_index")
    clients = PipelineClients(llm_client=client, pinecone_index=fake_pinecone_index)

    marker = build_marker("questionnaire_sent", anomaly=ANOMALY)
    prompt = f"{marker}\n{_ten_answers_reply()}"

    result = run_pipeline(prompt, clients)

    assert keyword_mock.called
    assert not pinecone_mock.called
    assert result["response"] == "Summary via keyword fallback."


def _no_op_keyword_retrieval(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline, "retrieve_context_keyword",
        lambda direction, answers: {"table_matches": [], "rag_snippet": ""},
    )


def test_react_response_missing_findings_key_normalizes_instead_of_key_error(monkeypatch):
    """A ReAct Agent response that omits `findings` entirely must not raise KeyError.

    The key is normalized to an empty list and handed to Confidence Classification,
    the same way run_react_agent's forced-final branch already normalizes it.
    """
    _no_op_keyword_retrieval(monkeypatch)
    react_response = json.dumps({"need_more_info": False, "followup_question": None})
    confidence_response = json.dumps({"findings": []})
    summary_response = json.dumps({"parent_summary": "No clear cause identified."})
    client = _client_with_responses(react_response, confidence_response, summary_response)
    clients = PipelineClients(llm_client=client)

    marker = build_marker("questionnaire_sent", anomaly=ANOMALY)

    result = run_pipeline(f"{marker}\n{_ten_answers_reply()}", clients)

    assert result["response"] == "No clear cause identified."
    confidence_call = client.chat.completions.create.call_args_list[1]
    confidence_payload = json.loads(confidence_call.kwargs["messages"][1]["content"])
    assert confidence_payload["findings"] == []


def test_followup_requested_without_question_raises_pipeline_error(monkeypatch):
    _no_op_keyword_retrieval(monkeypatch)
    react_response = json.dumps({"need_more_info": True, "followup_question": None, "findings": None})
    client = _client_with_responses(react_response)
    clients = PipelineClients(llm_client=client)

    marker = build_marker("questionnaire_sent", anomaly=ANOMALY)

    with pytest.raises(PipelineError, match="did not provide a question"):
        run_pipeline(f"{marker}\n{_ten_answers_reply()}", clients)


def test_missing_parent_summary_text_raises_pipeline_error(monkeypatch):
    _no_op_keyword_retrieval(monkeypatch)
    react_response = json.dumps({
        "need_more_info": False, "followup_question": None,
        "findings": [{"cause": "exercise", "evidence": "e", "source": "answers"}],
    })
    confidence_response = json.dumps({
        "findings": [{"cause": "exercise", "evidence": "e", "confidence": "low", "rationale": "r"}],
    })
    summary_response = json.dumps({"summary": "wrong key"})
    client = _client_with_responses(react_response, confidence_response, summary_response)
    clients = PipelineClients(llm_client=client)

    marker = build_marker("questionnaire_sent", anomaly=ANOMALY)

    with pytest.raises(PipelineError, match="Parent Summary did not return the expected text"):
        run_pipeline(f"{marker}\n{_ten_answers_reply()}", clients)


def test_marker_with_invalid_anomaly_direction_raises_pipeline_error():
    """The turn-2/3 marker is client-held and never re-validated by extract_conversation_state,
    so run_pipeline must reject an unexpected direction rather than let retrieval KeyError."""
    client = _client_with_responses()  # must fail before any LLM call
    clients = PipelineClients(llm_client=client)

    bad_anomaly = {**ANOMALY, "direction": "sideways"}
    marker = build_marker(
        "followup_sent", anomaly=bad_anomaly, answers=ALL_TEN_ANSWERS, notes="",
        followup_question="q?",
    )

    with pytest.raises(PipelineError, match="invalid anomaly"):
        run_pipeline(f"{marker}\nsome answer", clients)

    assert not client.chat.completions.create.called


def test_followup_marker_without_answers_field_defaults_to_empty_dict(monkeypatch):
    """`answers` is Optional on ConversationState; a marker missing it must not
    reach retrieval as None (which would AttributeError on answers.get(...))."""
    seen = {}

    def fake_keyword(direction, answers):
        seen["answers"] = answers
        return {"table_matches": [], "rag_snippet": ""}

    monkeypatch.setattr(agent_pipeline, "retrieve_context_keyword", fake_keyword)

    react_response = json.dumps({
        "need_more_info": False, "followup_question": None,
        "findings": [{"cause": "stress", "evidence": "e", "source": "answers"}],
    })
    confidence_response = json.dumps({
        "findings": [{"cause": "stress", "evidence": "e", "confidence": "low", "rationale": "r"}],
    })
    summary_response = json.dumps({"parent_summary": "Summary without stored answers."})
    client = _client_with_responses(react_response, confidence_response, summary_response)
    clients = PipelineClients(llm_client=client)

    marker = build_marker("followup_sent", anomaly=ANOMALY, notes="", followup_question="q?")

    result = run_pipeline(f"{marker}\nsome answer", clients)

    assert seen["answers"] == {}
    assert result["response"] == "Summary without stored answers."


def test_chained_real_transcript_reaches_final_summary(monkeypatch):
    """End-to-end chaining through real responses, not hand-built markers.

    Mirrors local_prototype.py's accumulation pattern
    (`transcript = f"{transcript}\\n{result['response']}\\n{reply}"`) across all
    three turns, so the questionnaire_sent -> followup_sent marker handoff is
    exercised exactly as a real client would drive it.
    """
    _no_op_keyword_retrieval(monkeypatch)

    react_followup = json.dumps({
        "need_more_info": True, "followup_question": "כמה זמן אחרי האוכל מדדת?", "findings": None,
    })
    react_final = json.dumps({
        "need_more_info": False, "followup_question": None,
        "findings": [{"cause": "late meal", "evidence": "answered 10 minutes", "source": "answers"}],
    })
    confidence_response = json.dumps({
        "findings": [{"cause": "late meal", "evidence": "e", "confidence": "high", "rationale": "r"}],
    })
    summary_response = json.dumps({"parent_summary": "Chained final summary."})
    client = _client_with_responses(
        react_followup, react_final, confidence_response, summary_response
    )
    clients = PipelineClients(llm_client=client)

    # Turn 1: fresh prompt -> questionnaire
    transcript = json.dumps(ANOMALY)
    turn1 = run_pipeline(transcript, clients)
    assert "SUGARBUDDY_CONTEXT" in turn1["response"]

    # Turn 2: accumulated transcript + questionnaire answers -> follow-up question
    transcript = f"{transcript}\n{turn1['response']}\n{_ten_answers_reply()}"
    turn2 = run_pipeline(transcript, clients)
    assert "כמה זמן אחרי האוכל מדדת?" in turn2["response"]
    assert extract_conversation_state(turn2["response"]).stage == "followup_sent"

    # Turn 3: accumulated transcript + follow-up answer -> final summary
    transcript = f"{transcript}\n{turn2['response']}\nכעשר דקות אחרי"
    turn3 = run_pipeline(transcript, clients)

    assert turn3["response"] == "Chained final summary."
    assert "SUGARBUDDY_CONTEXT" not in turn3["response"]
    assert [s["module"] for s in turn3["steps"]] == [
        "ReAct Agent", "Confidence Classification", "Parent Summary",
    ]
    # The turn-3 ReAct call must carry the answers and follow-up recovered from
    # the chained transcript's marker, not a fresh/empty state.
    react_payload = json.loads(
        client.chat.completions.create.call_args_list[1].kwargs["messages"][1]["content"]
    )
    assert react_payload["questionnaire_answers"] == dict.fromkeys(ALL_TEN_ANSWERS, True)
    assert react_payload["followup_question"] == "כמה זמן אחרי האוכל מדדת?"
    assert react_payload["followup_answer"] == "כעשר דקות אחרי"
