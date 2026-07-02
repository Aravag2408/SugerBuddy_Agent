"""Local, zero-cost prototype: CGM anomaly -> questionnaire -> agent-call stub."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sugarbuddy_anomaly_detector import (
    Anomaly,
    AnomalyDetector,
    AnomalySeverity,
    AnomalyType,
    SugarBuddyConfig,
)

DATA_DIR = Path(__file__).parent / "data"
NIGHTSCOUT_TEST_URL = "https://ggns2.fly.dev/"

FALLBACK_ANOMALY = Anomaly(
    type=AnomalyType.GLUCOSE_EXTREME,
    severity=AnomalySeverity.WARNING,
    message=(
        "Glucose rose to 260 mg/dL (threshold: 180 mg/dL). "
        "New high — not present in the last two readings."
    ),
    timestamp=datetime.now(timezone.utc),
    details={"sgv": 260, "threshold": 180, "direction": "high"},
)


def get_anomaly(config: SugarBuddyConfig) -> tuple[Anomaly, str]:
    try:
        detector = AnomalyDetector(config)
        anomalies = detector.check_for_anomalies()
    except Exception:
        anomalies = []
    if anomalies:
        return anomalies[0], "live"
    return FALLBACK_ANOMALY, "fallback"


def derive_direction(anomaly: Anomaly) -> str | None:
    if anomaly.type == AnomalyType.GLUCOSE_EXTREME:
        return anomaly.details.get("direction")
    if anomaly.type == AnomalyType.RATE_OF_CHANGE:
        roc = anomaly.details.get("roc_mgdl_per_min", 0)
        return "high" if roc > 0 else "low"
    if anomaly.type == AnomalyType.IOB_CONTEXTUAL:
        return "low"
    return None  # BIG_GAP carries no glucose-direction information


QUESTIONS: list[tuple[str, str]] = [
    ("ate_recently", "אכלת משהו בתוך השעתיים האחרונות?"),
    ("carb_count_accurate", "האם הזנת כמות מדוייקת של פחמימות או בערך?"),
    ("exercised_last_4h", "רצת, קפצת, או עשית שיעור ספורט ואימון ב-4 השעות האחרונות?"),
    ("stressed_last_30min", "מישהו הרגיז אותך או שהיית בלחץ גדול בחצי השעה האחרונה?"),
    ("drank_water_today", "שתית לפחות 4 כוסות מים במהלך היום?"),
    ("hot_weather_last_30min", "האם היית בחוץ במזג אוויר חם מאוד בחצי השעה האחרונה?"),
    ("correction_dose_last_3h", "החלפת משאבה או לקחת מנת תיקון (או פחמימות מהירות להיפו) ב-3 השעות האחרונות?"),
    ("phone_sensor_check_last_hour", "האם היית צמודה לטלפון הנייד בשעה האחרונה, והאם בדקת שהחיישן והמשאבה מחוברים חזק לעור?"),
    ("accurate_meals_today", "האם אכלת ארוחות מדוייקות היום?"),
]


def _ask_yes_no(question_text: str) -> bool:
    while True:
        raw = input(f"{question_text} (y/n): ").strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("Please answer y or n.")


def ask_questionnaire() -> dict:
    answers: dict = {}
    for key, text in QUESTIONS:
        answers[key] = _ask_yes_no(text)
    answers["notes"] = input("Notes (optional, press Enter to skip): ").strip()
    return answers


KEYWORD_MAP: list[tuple[str, bool, list[str]]] = [
    ("ate_recently", False, ["ארוחות"]),
    ("carb_count_accurate", False, ["פחמימות"]),
    ("exercised_last_4h", True, ["פעילות גופנית"]),
    ("stressed_last_30min", True, ["סטרס", "לחץ"]),
    ("hot_weather_last_30min", True, ["חום", "מזג אוויר"]),
    ("correction_dose_last_3h", True, ["תיקון"]),
    ("phone_sensor_check_last_hour", False, ["טלפון"]),
    ("accurate_meals_today", False, ["ארוחות"]),
]

STATE_BY_DIRECTION = {"high": "היפר", "low": "היפו"}

RAG_FILES: dict[str, list[Path]] = {
    "high": [DATA_DIR / "rag" / "ada_diabetes_association.txt"],
    "low": [
        DATA_DIR / "rag" / "ada_diabetes_association.txt",
        DATA_DIR / "rag" / "niddk_hypoglycemia.txt",
    ],
}


def _load_table() -> list[dict]:
    with open(DATA_DIR / "investigation_table.json", encoding="utf-8") as f:
        return json.load(f)


def _extract_rag_section(text: str, direction: str) -> str:
    marker = "## HYPERGLYCEMIA" if direction == "high" else "## HYPOGLYCEMIA"
    other_marker = "## HYPOGLYCEMIA" if direction == "high" else "## HYPERGLYCEMIA"
    if marker not in text:
        return ""
    section = text.split(marker, 1)[1]
    if other_marker in section:
        section = section.split(other_marker, 1)[0]
    return section.strip()


def retrieve_context(anomaly: Anomaly, answers: dict) -> dict:
    direction = derive_direction(anomaly)
    if direction is None:
        return {"table_matches": [], "rag_snippet": ""}

    state = STATE_BY_DIRECTION[direction]
    table = [row for row in _load_table() if row["state"] == state]

    matches: list[dict] = []
    for key, trigger, keywords in KEYWORD_MAP:
        if answers.get(key) != trigger:
            continue
        for row in table:
            haystack = row["category"] + " " + row["cause"]
            if any(kw in haystack for kw in keywords) and row not in matches:
                matches.append(row)

    matches = matches[:3]

    rag_snippet = ""
    for path in RAG_FILES.get(direction, []):
        text = path.read_text(encoding="utf-8")
        rag_snippet += _extract_rag_section(text, direction) + "\n\n"

    return {"table_matches": matches, "rag_snippet": rag_snippet.strip()}
