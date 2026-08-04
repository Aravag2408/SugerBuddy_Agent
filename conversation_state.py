from __future__ import annotations
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
    return f"{MARKER_PREFIX}{json.dumps(payload, ensure_ascii=False)}{MARKER_SUFFIX}"


def extract_conversation_state(prompt: str) -> ConversationState | None:
    matches = list(_MARKER_PATTERN.finditer(prompt))
    if not matches:
        return None

    last_match = matches[-1]
    try:
        payload = json.loads(last_match.group(1))
    except json.JSONDecodeError:
        return None

    return ConversationState(
        stage=payload.get("stage", ""),
        anomaly=payload.get("anomaly", {}),
        answers=payload.get("answers"),
        notes=payload.get("notes", ""),
        followup_question=payload.get("followup_question"),
        reply_text=prompt[last_match.end():].strip(),
    )
