from __future__ import annotations
import re

from conversation_state import build_marker
from errors import PipelineError

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
    ("finger_stick_or_calibration_recent", "האם עשית בדיקה באצבע או כיול לאחרונה?"),
]

_ANSWER_LINE = re.compile(r"(\d+)\.\s*(Y|N|Yes|No|כן|לא)\b", re.IGNORECASE)
_YES_VALUES = {"y", "yes", "כן"}


def format_questionnaire_prompt(anomaly: dict) -> str:
    lines = [
        "Thanks — before I can investigate, please answer these yes/no questions.",
        'Reply as a numbered list, e.g. "1. Y 2. N 3. Y ...". You may add notes after the list.',
        "",
    ]
    for i, (_, text) in enumerate(QUESTIONS, start=1):
        lines.append(f"{i}. {text}")
    lines.append("")
    lines.append(build_marker("questionnaire_sent", anomaly=anomaly))
    return "\n".join(lines)


def parse_answers(reply_text: str) -> tuple[dict[str, bool], str]:
    found: dict[int, bool] = {}
    last_end = 0
    for m in _ANSWER_LINE.finditer(reply_text):
        index = int(m.group(1))
        if 1 <= index <= len(QUESTIONS) and index not in found:
            found[index] = m.group(2).strip().lower() in _YES_VALUES
            last_end = m.end()
            if len(found) == len(QUESTIONS):
                break

    if len(found) < len(QUESTIONS):
        raise PipelineError(
            "could not parse all questionnaire answers; reply as a numbered Y/N list"
        )

    answers = {QUESTIONS[i - 1][0]: found[i] for i in range(1, len(QUESTIONS) + 1)}
    notes = reply_text[last_end:].strip()
    return answers, notes
