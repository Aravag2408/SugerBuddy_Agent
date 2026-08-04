import supabase_log


def test_log_execution_swallows_client_construction_errors(monkeypatch):
    def raise_error():
        raise RuntimeError("supabase down")

    monkeypatch.setattr(supabase_log, "_get_client", raise_error)

    supabase_log.log_execution("prompt", "response", [{"module": "x"}])  # must not raise


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

    supabase_log.log_execution("prompt text", "response text", [{"module": "CGM Event"}])

    assert calls["table_name"] == "execution_log"
    assert calls["payload"]["prompt"] == "prompt text"
    assert calls["payload"]["response"] == "response text"
    assert '"module": "CGM Event"' in calls["payload"]["steps"]
    assert calls["executed"] is True
