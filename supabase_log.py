"""Non-blocking audit log of /api/execute calls. Logging failures must
never propagate to the caller — this is a side effect, not part of the
pipeline's contract.

SUPABASE_KEY must be the service-role key and must stay server-side only:
execution_log has row level security enabled with a service-role-only policy
(see supabase/migration.sql), so the anon/public key cannot insert here.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

import config

_client = None


def _get_client():
    global _client
    if _client is None:
        from supabase import create_client
        _client = create_client(
            config.require(config.SUPABASE_URL, "SUPABASE_URL"),
            config.require(config.SUPABASE_KEY, "SUPABASE_KEY"),
        )
    return _client


def _dump(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)


def log_execution(prompt: str, response: str | None, steps: list[dict], log_fields: dict) -> None:
    try:
        client = _get_client()
        client.table("execution_log").insert({
            "prompt": prompt,
            "response": response,
            "steps": json.dumps(steps, ensure_ascii=False),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "stage": log_fields["stage"],
            "anomaly": _dump(log_fields["anomaly"]),
            "questionnaire_answers": _dump(log_fields["questionnaire_answers"]),
            "notes": log_fields["notes"],
            "retrieved_context": _dump(log_fields["retrieved_context"]),
            "react_findings": _dump(log_fields["react_findings"]),
            "need_more_info": log_fields["need_more_info"],
            "confidence_result": _dump(log_fields["confidence_result"]),
            "parent_summary": log_fields["parent_summary"],
            "followup_question": log_fields["followup_question"],
            "followup_answer": log_fields["followup_answer"],
        }).execute()
    except Exception as e:
        print(f"[supabase_log] failed to log execution (non-fatal): {e}")
