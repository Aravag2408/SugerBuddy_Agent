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


def test_build_and_extract_with_field_containing_marker_delimiter():
    """Regression test: field values containing the literal substring ' -->' must not truncate the marker."""
    anomaly = {"type": "glucose_extreme", "severity": "urgent", "direction": "high",
               "message": "m", "details": {}}
    # notes field intentionally contains the marker delimiter
    marker = build_marker(
        "followup_sent", anomaly=anomaly, answers={}, notes="See HTML comment: -->",
        followup_question="q?"
    )
    prompt = f"Question\n{marker}\nReply text"

    state = extract_conversation_state(prompt)

    # Should successfully extract despite the ' -->' in notes field
    assert state is not None
    assert state.stage == "followup_sent"
    assert state.notes == "See HTML comment: -->"
    assert state.reply_text == "Reply text"


def test_extract_returns_none_on_non_dict_json_payload():
    """Regression test: valid JSON that is not a dict should return None, not crash."""
    # Marker body is valid JSON but decodes to a non-dict (null in this case)
    prompt = "<!-- SUGARBUDDY_CONTEXT: null -->\nreply"
    assert extract_conversation_state(prompt) is None

    # Also test other valid JSON non-dict types
    prompt = "<!-- SUGARBUDDY_CONTEXT: 42 -->\nreply"
    assert extract_conversation_state(prompt) is None

    prompt = "<!-- SUGARBUDDY_CONTEXT: [1, 2, 3] -->\nreply"
    assert extract_conversation_state(prompt) is None
