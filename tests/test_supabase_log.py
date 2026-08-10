import json

import supabase_log


def _sample_log_fields(**overrides):
    fields = {
        "stage": "initial",
        "anomaly": {
            "type": "glucose_extreme", "severity": "urgent", "direction": "high",
            "message": "m", "details": {},
        },
        "questionnaire_answers": None,
        "notes": None,
        "retrieved_context": None,
        "react_findings": None,
        "need_more_info": None,
        "confidence_result": None,
        "parent_summary": None,
        "followup_question": None,
        "followup_answer": None,
    }
    fields.update(overrides)
    return fields


def test_log_execution_swallows_client_construction_errors(monkeypatch):
    def raise_error():
        raise RuntimeError("supabase down")

    monkeypatch.setattr(supabase_log, "_get_client", raise_error)

    supabase_log.log_execution("prompt", "response", [{"module": "x"}], _sample_log_fields())  # must not raise


def test_log_execution_inserts_expected_payload(monkeypatch):
    calls = {}

    class FakeTable:
        def insert(self, payload):
            calls["payload"] = payload
            return self

        def execute(self):
            calls["executed"] = True

    class FakeClient:
        def table(self, name):
            calls["table_name"] = name
            return FakeTable()

    monkeypatch.setattr(supabase_log, "_get_client", lambda: FakeClient())

    log_fields = _sample_log_fields()
    supabase_log.log_execution("prompt text", "response text", [{"module": "CGM Event"}], log_fields)

    assert calls["table_name"] == "execution_log"
    assert calls["payload"]["prompt"] == "prompt text"
    assert calls["payload"]["response"] == "response text"
    assert '"module": "CGM Event"' in calls["payload"]["steps"]
    assert calls["payload"]["stage"] == "initial"
    assert json.loads(calls["payload"]["anomaly"]) == log_fields["anomaly"]
    assert calls["payload"]["questionnaire_answers"] is None
    assert calls["payload"]["notes"] is None
    assert calls["payload"]["need_more_info"] is None
    assert calls["executed"] is True


def test_log_execution_encodes_hebrew_jsonb_fields_without_ascii_escaping(monkeypatch):
    calls = {}

    class FakeTable:
        def insert(self, payload):
            calls["payload"] = payload
            return self

        def execute(self):
            pass

    class FakeClient:
        def table(self, name):
            return FakeTable()

    monkeypatch.setattr(supabase_log, "_get_client", lambda: FakeClient())

    log_fields = _sample_log_fields(
        stage="questionnaire_sent",
        questionnaire_answers={"ate_recently": True},
        notes="הערה בעברית",
        retrieved_context={"table_matches": [], "rag_snippet": "טקסט"},
        react_findings=[{"cause": "מתח", "evidence": "e", "source": "answers"}],
        need_more_info=False,
        confidence_result={"findings": [{"cause": "מתח", "confidence": "medium"}]},
        parent_summary="סיכום בעברית",
        followup_question="שאלה?",
        followup_answer="תשובה",
    )

    supabase_log.log_execution("p", "r", [], log_fields)

    payload = calls["payload"]
    assert "מתח" in payload["react_findings"]
    assert "\\u" not in payload["react_findings"]
    assert payload["notes"] == "הערה בעברית"
    assert payload["parent_summary"] == "סיכום בעברית"
    assert payload["followup_question"] == "שאלה?"
    assert payload["followup_answer"] == "תשובה"
    assert payload["need_more_info"] is False
    assert json.loads(payload["confidence_result"])["findings"][0]["cause"] == "מתח"
