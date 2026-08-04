import pytest
from questionnaire import QUESTIONS, format_questionnaire_prompt, parse_answers
from conversation_state import extract_conversation_state
from errors import PipelineError

ANOMALY = {"type": "glucose_extreme", "severity": "urgent", "direction": "high",
           "message": "m", "details": {}}


def test_questions_list_has_ten_entries_in_order():
    assert len(QUESTIONS) == 10
    assert QUESTIONS[0][0] == "ate_recently"
    assert QUESTIONS[9][0] == "finger_stick_or_calibration_recent"
    assert QUESTIONS[9][1] == "האם עשית בדיקה באצבע או כיול לאחרונה?"


def test_format_questionnaire_prompt_includes_all_questions_and_marker():
    text = format_questionnaire_prompt(ANOMALY)
    for i, (_, question_text) in enumerate(QUESTIONS, start=1):
        assert f"{i}. {question_text}" in text
    assert "SUGARBUDDY_CONTEXT" in text

    # conversation_state.build_marker base64-encodes the payload (fixed during
    # Task 2's review to avoid delimiter collisions), so assert via a real
    # round-trip rather than checking for literal JSON text in the marker.
    state = extract_conversation_state(text)
    assert state is not None
    assert state.stage == "questionnaire_sent"
    assert state.anomaly == ANOMALY


def test_parse_answers_all_yes_english():
    reply = "\n".join(f"{i}. Y" for i in range(1, 11))
    answers, notes = parse_answers(reply)
    assert all(answers.values())
    assert len(answers) == 10
    assert notes == ""


def test_parse_answers_mixed_hebrew_and_notes():
    reply = "1. כן\n2. לא\n3. Y\n4. N\n5. Yes\n6. No\n7. כן\n8. לא\n9. Y\n10. N\nהערה: ישנתי מאוחר"
    answers, notes = parse_answers(reply)
    assert answers["ate_recently"] is True
    assert answers["carb_count_accurate"] is False
    assert notes == "הערה: ישנתי מאוחר"


def test_parse_answers_raises_when_fewer_than_ten():
    reply = "1. Y\n2. N\n3. Y"
    with pytest.raises(PipelineError, match="numbered Y/N list"):
        parse_answers(reply)


def test_parse_answers_notes_with_spurious_answer_pattern():
    # Regression test: notes containing a substring matching the answer-line
    # pattern (e.g. "6. לא") must not overwrite real answers or truncate notes.
    reply = "1. כן\n2. לא\n3. Y\n4. N\n5. Yes\n6. Yes\n7. כן\n8. לא\n9. Y\n10. N\nנ.ב. קמתי בשעה 6. לא ישנתי טוב בכלל"
    answers, notes = parse_answers(reply)
    # Question 6 (hot_weather_last_30min) should remain True from answer "6. Yes",
    # not overwritten by spurious "6. לא" (False) in the notes.
    assert answers["hot_weather_last_30min"] is True
    # Notes should NOT be truncated at the spurious "6. לא" inside the actual notes
    assert notes == "נ.ב. קמתי בשעה 6. לא ישנתי טוב בכלל"
    assert "קמתי בשעה" in notes  # Full notes preserved
