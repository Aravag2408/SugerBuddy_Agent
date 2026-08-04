from __future__ import annotations
import json
from pathlib import Path

import config
from llm_client import embed_text
from questionnaire import QUESTIONS

DATA_DIR = Path(__file__).parent / "data"

STATE_BY_DIRECTION = {"high": "היפר", "low": "היפו"}

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

RAG_FILES: dict[str, list[Path]] = {
    "high": [DATA_DIR / "rag" / "ada_diabetes_association.txt"],
    "low": [
        DATA_DIR / "rag" / "ada_diabetes_association.txt",
        DATA_DIR / "rag" / "niddk_hypoglycemia.txt",
    ],
}


def load_table() -> list[dict]:
    with open(DATA_DIR / "investigation_table.json", encoding="utf-8") as f:
        return json.load(f)


def extract_rag_section(text: str, direction: str) -> str:
    marker = "## HYPERGLYCEMIA" if direction == "high" else "## HYPOGLYCEMIA"
    other_marker = "## HYPOGLYCEMIA" if direction == "high" else "## HYPERGLYCEMIA"
    if marker not in text:
        return ""
    section = text.split(marker, 1)[1]
    if other_marker in section:
        section = section.split(other_marker, 1)[0]
    return section.strip()


def retrieve_context_keyword(direction: str | None, answers: dict) -> dict:
    if direction is None:
        return {"table_matches": [], "rag_snippet": ""}

    state = STATE_BY_DIRECTION[direction]
    table = [row for row in load_table() if row["state"] == state]

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
        rag_snippet += extract_rag_section(text, direction) + "\n\n"

    return {"table_matches": matches, "rag_snippet": rag_snippet.strip()}


def get_pinecone_index():
    from pinecone import Pinecone
    pc = Pinecone(api_key=config.require(config.PINECONE_API_KEY, "PINECONE_API_KEY"))
    return pc.Index(config.PINECONE_INDEX_NAME)


def get_pinecone_index_safe():
    try:
        return get_pinecone_index()
    except Exception:
        return None


def _build_query_text(direction: str, answers: dict) -> str:
    yes_texts = [text for key, text in QUESTIONS if answers.get(key)]
    return f"glucose direction: {direction}. " + " ".join(yes_texts)


def retrieve_context_pinecone(direction, answers, embed_client, pinecone_index) -> dict:
    if direction is None:
        return {"table_matches": [], "rag_snippet": ""}

    try:
        query_text = _build_query_text(direction, answers)
        vector = embed_text(embed_client, query_text)
        state = STATE_BY_DIRECTION[direction]

        causes_result = pinecone_index.query(
            vector=vector, top_k=3, namespace="causes",
            filter={"state": {"$eq": state}}, include_metadata=True,
        )
        table_matches = [match.metadata for match in causes_result.matches]

        reference_result = pinecone_index.query(
            vector=vector, top_k=2, namespace="reference",
            filter={"direction": {"$eq": direction}}, include_metadata=True,
        )
        rag_snippet = "\n\n".join(match.metadata["text"] for match in reference_result.matches)

        return {"table_matches": table_matches, "rag_snippet": rag_snippet}
    except Exception:
        return retrieve_context_keyword(direction, answers)
