from __future__ import annotations
import base64
import json
import re
from dataclasses import dataclass
from typing import Optional

MARKER_PREFIX = "<!-- SUGARBUDDY_CONTEXT: "
MARKER_SUFFIX = " -->"

_MARKER_PATTERN = re.compile(
    re.escape(MARKER_PREFIX) + r"(.*?)" + re.escape(MARKER_SUFFIX), re.DOTALL
)


@dataclass
class ConversationState:
    stage: str
    anomaly: dict
    answers: Optional[dict] = None
    notes: str = ""
    followup_question: Optional[str] = None
    reply_text: str = ""


def build_marker(stage: str, **fields) -> str:
    payload = {"stage": stage, **fields}
    json_bytes = json.dumps(payload, ensure_ascii=False).encode()
    encoded = base64.b64encode(json_bytes).decode()
    return f"{MARKER_PREFIX}{encoded}{MARKER_SUFFIX}"


def extract_conversation_state(prompt: str) -> ConversationState | None:
    matches = list(_MARKER_PATTERN.finditer(prompt))
    if not matches:
        return None

    last_match = matches[-1]
    try:
        encoded_payload = last_match.group(1)
        json_bytes = base64.b64decode(encoded_payload)
        payload = json.loads(json_bytes.decode())
    except (base64.binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    return ConversationState(
        stage=payload.get("stage", ""),
        anomaly=payload.get("anomaly", {}),
        answers=payload.get("answers"),
        notes=payload.get("notes", ""),
        followup_question=payload.get("followup_question"),
        reply_text=prompt[last_match.end():].strip(),
    )
