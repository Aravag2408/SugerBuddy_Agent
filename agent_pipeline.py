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


REACT_SYSTEM_PROMPT_BASE = (
    "You are a diabetes event investigation assistant for a parent-teen pair. Given a "
    "CGM anomaly, structured yes/no answers with free-text notes, retrieved "
    "candidate-cause table rows, and medical reference text, reason step by step. If "
    "one additional piece of information from the teen would meaningfully change your "
    "findings, return ONLY JSON: {\"need_more_info\": true, \"followup_question\": "
    "\"<your question, in Hebrew>\", \"findings\": null}. Otherwise return ONLY JSON: "
    "{\"need_more_info\": false, \"followup_question\": null, \"findings\": "
    "[{\"cause\": str, \"evidence\": str, \"source\": \"table\"|\"reference\"|\"answers\"}]}. "
    "List up to 3 findings ordered by plausibility. Do not diagnose or invent facts not "
    "supported by the given context."
)

REACT_FORCED_FINAL_SUFFIX = (
    " You must set need_more_info to false and provide findings now — no further "
    "follow-up is allowed."
)


def _build_react_user_prompt(anomaly, answers, notes, context, followup=None) -> str:
    payload = {
        "anomaly": anomaly,
        "questionnaire_answers": answers,
        "notes": notes,
        "candidate_causes": context["table_matches"],
        "reference_text": context["rag_snippet"],
    }
    if followup:
        payload["followup_question"] = followup["question"]
        payload["followup_answer"] = followup["answer"]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def run_react_agent(
    anomaly, answers, notes, context, llm_client, followup=None, allow_followup=True
) -> tuple[dict, dict]:
    system_prompt = REACT_SYSTEM_PROMPT_BASE
    if not allow_followup:
        system_prompt += REACT_FORCED_FINAL_SUFFIX

    user_prompt = _build_react_user_prompt(anomaly, answers, notes, context, followup)
    parsed, step = chat_json(llm_client, "ReAct Agent", system_prompt, user_prompt)

    if not allow_followup and parsed.get("need_more_info"):
        parsed = {
            "need_more_info": False,
            "followup_question": None,
            "findings": parsed.get("findings") or [],
        }

    return parsed, step


CONFIDENCE_SYSTEM_PROMPT = (
    "You score confidence for each candidate finding about what caused a glucose "
    "anomaly. Given the anomaly, questionnaire answers, and a list of candidate "
    "findings with their supporting evidence, return ONLY JSON: {\"findings\": "
    "[{\"cause\": str, \"evidence\": str, \"confidence\": \"low\"|\"medium\"|\"high\", "
    "\"rationale\": str}]}, preserving each finding's cause/evidence and adding "
    "confidence and a one-sentence rationale. Base confidence on how directly the "
    "evidence supports each cause."
)

PARENT_SUMMARY_SYSTEM_PROMPT = (
    "You write a parent-facing summary of a glucose anomaly investigation. Given the "
    "anomaly, the teen's questionnaire answers, and confidence-scored candidate "
    "findings, return ONLY JSON: {\"parent_summary\": str}. parent_summary must read "
    "as: a 2-3 sentence recap of the event and what the teen reported, then up to "
    "three possible reasons ordered by confidence (each stated with its confidence "
    "level), then one practical suggestion. Do not diagnose; present reasons as "
    "possibilities, not conclusions."
)


def run_confidence_classification(anomaly, answers, findings, llm_client) -> tuple[dict, dict]:
    user_prompt = json.dumps(
        {"anomaly": anomaly, "questionnaire_answers": answers, "findings": findings},
        ensure_ascii=False, indent=2,
    )
    return chat_json(llm_client, "Confidence Classification", CONFIDENCE_SYSTEM_PROMPT, user_prompt)


def run_parent_summary(anomaly, answers, findings, llm_client) -> tuple[dict, dict]:
    user_prompt = json.dumps(
        {"anomaly": anomaly, "questionnaire_answers": answers, "findings": findings},
        ensure_ascii=False, indent=2,
    )
    return chat_json(llm_client, "Parent Summary", PARENT_SUMMARY_SYSTEM_PROMPT, user_prompt)


from dataclasses import dataclass

from conversation_state import build_marker, extract_conversation_state
from questionnaire import format_questionnaire_prompt, parse_answers
from retrieval import retrieve_context_keyword, retrieve_context_pinecone


@dataclass
class PipelineClients:
    llm_client: object
    pinecone_index: object = None
    embed_client: object = None


def _retrieve_context(anomaly: dict, answers: dict, clients: PipelineClients) -> dict:
    direction = anomaly.get("direction")
    if clients.pinecone_index is not None and clients.embed_client is not None:
        return retrieve_context_pinecone(direction, answers, clients.embed_client, clients.pinecone_index)
    return retrieve_context_keyword(direction, answers)


def _finalize(anomaly, answers, findings, clients: PipelineClients, prior_steps: list[dict]) -> dict:
    confidence_result, confidence_step = run_confidence_classification(
        anomaly, answers, findings, clients.llm_client
    )
    summary_result, summary_step = run_parent_summary(
        anomaly, answers, confidence_result["findings"], clients.llm_client
    )
    return {
        "response": summary_result["parent_summary"],
        "steps": prior_steps + [confidence_step, summary_step],
    }


def run_pipeline(prompt: str, clients: PipelineClients) -> dict:
    state = extract_conversation_state(prompt)

    if state is None or state.stage not in ("questionnaire_sent", "followup_sent"):
        anomaly, steps = parse_cgm_event(prompt, clients.llm_client)
        return {"response": format_questionnaire_prompt(anomaly), "steps": steps}

    if state.stage == "questionnaire_sent":
        answers, notes = parse_answers(state.reply_text)
        context = _retrieve_context(state.anomaly, answers, clients)
        result, react_step = run_react_agent(state.anomaly, answers, notes, context, clients.llm_client)

        if result.get("need_more_info"):
            marker = build_marker(
                "followup_sent", anomaly=state.anomaly, answers=answers, notes=notes,
                followup_question=result["followup_question"],
            )
            return {"response": f"{result['followup_question']}\n\n{marker}", "steps": [react_step]}

        return _finalize(state.anomaly, answers, result["findings"], clients, [react_step])

    # state.stage == "followup_sent"
    followup_answer = state.reply_text
    context = _retrieve_context(state.anomaly, state.answers, clients)
    result, react_step = run_react_agent(
        state.anomaly, state.answers, state.notes, context, clients.llm_client,
        followup={"question": state.followup_question, "answer": followup_answer},
        allow_followup=False,
    )
    return _finalize(state.anomaly, state.answers, result["findings"], clients, [react_step])
