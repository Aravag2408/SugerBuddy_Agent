"""Non-blocking audit log of /api/execute calls. Logging failures must
never propagate to the caller — this is a side effect, not part of the
pipeline's contract.
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


def log_execution(prompt: str, response: str | None, steps: list[dict]) -> None:
    try:
        client = _get_client()
        client.table("execution_log").insert({
            "prompt": prompt,
            "response": response,
            "steps": json.dumps(steps, ensure_ascii=False),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        print(f"[supabase_log] failed to log execution (non-fatal): {e}")
