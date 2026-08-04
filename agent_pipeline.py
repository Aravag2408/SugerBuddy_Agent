"""Core reasoning pipeline: CGM event parsing, the bounded ReAct Agent,
Confidence Classification, Parent Summary, and the run_pipeline orchestrator
that ties them together across the multi-turn conversation.
"""
from __future__ import annotations
import json
import re

from errors import PipelineError
from llm_client import chat_json

ALLOWED_TYPES = {"rate_of_change", "big_gap", "iob_contextual", "glucose_extreme"}
ALLOWED_SEVERITIES = {"warning", "urgent"}
ALLOWED_DIRECTIONS = {"high", "low", None}

CGM_EVENT_SYSTEM_PROMPT = (
    "Extract a CGM (continuous glucose monitor) event from the user's description. "
    "Return ONLY JSON: {\"type\": str, \"severity\": str, \"direction\": str|null, "
    "\"message\": str, \"details\": object}. type must be one of "
    "[rate_of_change, big_gap, iob_contextual, glucose_extreme]. severity must be one "
    "of [warning, urgent]. direction must be 'high', 'low', or null. If the "
    "description does not describe a glucose event, return "
    "{\"error\": \"not a CGM event description\"}."
)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _valid_anomaly_dict(candidate) -> bool:
    return (
        isinstance(candidate, dict)
        and candidate.get("type") in ALLOWED_TYPES
        and candidate.get("severity") in ALLOWED_SEVERITIES
        and candidate.get("direction", None) in ALLOWED_DIRECTIONS
        and isinstance(candidate.get("message"), str)
        and isinstance(candidate.get("details", {}), dict)
    )


def _try_parse_json_shortcut(prompt: str) -> dict | None:
    match = _JSON_BLOCK.search(prompt)
    if not match:
        return None
    try:
        candidate = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not _valid_anomaly_dict(candidate):
        return None
    candidate.setdefault("details", {})
    return candidate


def parse_cgm_event(prompt: str, llm_client) -> tuple[dict, list[dict]]:
    shortcut = _try_parse_json_shortcut(prompt)
    if shortcut is not None:
        return shortcut, []

    parsed, step = chat_json(llm_client, "CGM Event", CGM_EVENT_SYSTEM_PROMPT, prompt)
    if parsed.get("error") or not _valid_anomaly_dict(parsed):
        raise PipelineError("not a recognizable CGM event description")
    parsed.setdefault("details", {})
    return parsed, [step]
