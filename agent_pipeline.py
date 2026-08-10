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
    "You are a diabetes event investigation assistant for a parent-teen pair. Given a CGM anomaly, "
    "structured yes/no answers with free-text notes, retrieved candidate-cause table rows, and medical reference text, "
    "reason step by step.\n\n"
    "CRITICAL DECISION RULE:\n"
    "1. If NONE of the retrieved candidate_causes directly explains the primary factor mentioned in the anomaly/notes (e.g., exercise, pizza, cannula issue),\n"
    "2. OR if one additional piece of information from the teen would meaningfully change your findings,\n"
    "3. OR if questionnaire answers contradict each other,\n"
    "you MUST set need_more_info to true and return ONLY JSON: "
    "{\"need_more_info\": true, \"followup_question\": \"<your question, in Hebrew>\", \"findings\": null}.\n\n"
    "Prefer asking or requesting missing context over listing weak/uncertain findings.\n"
    "OTHERWISE, return ONLY JSON: "
    "{\"need_more_info\": false, \"followup_question\": null, \"findings\": [{\"cause\": str, \"evidence\": str, \"source\": \"table\"|\"reference\"|\"answers\"}]}.\n"
    "List up to 3 findings ordered by plausibility. Do not diagnose or invent facts not supported by the given context.\n"
    "CRITICAL OUTPUT RULES:\n"
    "1. Output ONLY a valid JSON object. Do not wrap in markdown or add text before/after JSON.\n"
    "2. STOP immediately after the closing brace '}'."
)

REACT_FORCED_FINAL_SUFFIX = (
    " You must set need_more_info to false and provide findings now — no further follow-up is allowed."
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
    "You score confidence for each candidate finding about what caused a glucose anomaly. "
    "Given the anomaly, questionnaire answers, and a list of candidate findings with their supporting evidence, "
    "return ONLY valid JSON: {\"findings\": [{\"cause\": str, \"evidence\": str, \"confidence\": \"low\"|\"medium\"|\"high\", \"rationale\": str}]}.\n"
    "CRITICAL OUTPUT RULES:\n"
    "1. Output ONLY a single valid JSON object. No markdown, no code blocks (do NOT use ```json), no trailing text.\n"
    "2. STOP immediately after the closing JSON brace '}'.\n"
    "3. Preserve each finding's cause/evidence and add confidence and a one-sentence rationale.\n"
    "4. Base confidence on how directly the evidence supports each cause.\n"
    "5. Write every rationale in Hebrew; the confidence values themselves stay as literal English strings (low/medium/high)."
)

PARENT_SUMMARY_SYSTEM_PROMPT = (
    "You write a parent-facing summary of a glucose anomaly investigation. Given the anomaly, the teen's "
    "questionnaire answers, and confidence-scored candidate findings, return ONLY valid JSON: {\"parent_summary\": str}.\n\n"
    "CRITICAL OUTPUT RULES:\n"
    "1. Output ONLY a single valid JSON object with EXACTLY ONE KEY: {\"parent_summary\": str}.\n"
    "2. Do NOT create additional JSON keys (such as \"possible_reasons\", \"reasons\", \"suggestion\", or \"recap\"). "
    "ALL content (recap, reasons with confidence levels, and practical suggestion) MUST be combined into a single continuous text string assigned strictly to \"parent_summary\".\n"
    "3. No markdown wrappers, no code blocks (do NOT use ```json), no text before or after the JSON object.\n"
    "4. STOP immediately after the closing JSON brace '}'.\n"
    "5. Structure of parent_summary text:\n"
    "   - A 2-3 sentence recap of the event and what the teen reported.\n"
    "   - Before listing reasons, merge any candidate findings that describe the same underlying issue "
    "(e.g., several findings all pointing to irregular/skipped/inconsistent eating) into a single reason — "
    "keep only that group's highest-confidence finding and drop the rest. Only list reasons that are "
    "conceptually distinct from one another; never present overlapping or restated causes as separate reasons.\n"
    "   - Up to three possible reasons ordered by confidence (state each reason with its confidence level in Hebrew, e.g., 'בביטחון גבוה', 'בביטחון בינוני').\n"
    "   - One practical suggestion.\n"
    "6. Write parent_summary strictly in natural Hebrew. Use ONLY Hebrew text (no foreign characters or words from other languages such as Chinese or English, except numbers).\n"
    "7. Translate any technical terms to Hebrew. Do not diagnose; present reasons as possibilities, not conclusions."
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


def _build_log_fields(stage: str, anomaly: dict, **overrides) -> dict:
    fields = {
        "stage": stage,
        "anomaly": anomaly,
        "questionnaire_answers": None,
        "notes": None,
        "retrieved_context": None,
        "react_findings": None,
        "need_more_info": None,
        "confidence_result": None,
        "parent_summary": None,
        "followup_question": None,
        "followup_answer": None,
    }
    fields.update(overrides)
    return fields


def _finalize(
    anomaly, answers, findings, clients: PipelineClients, prior_steps: list[dict], log_fields: dict,
) -> dict:
    confidence_result, confidence_step = run_confidence_classification(
        anomaly, answers, findings, clients.llm_client
    )
    summary_result, summary_step = run_parent_summary(
        anomaly, answers, confidence_result.get("findings") or [], clients.llm_client
    )
    parent_summary = summary_result.get("parent_summary")
    if not isinstance(parent_summary, str) or not parent_summary.strip():
        raise PipelineError("Parent Summary did not return the expected text")
    log_fields["confidence_result"] = confidence_result
    log_fields["parent_summary"] = parent_summary
    return {
        "response": parent_summary,
        "steps": prior_steps + [confidence_step, summary_step],
        "log_fields": log_fields,
    }


def run_pipeline(prompt: str, clients: PipelineClients) -> dict:
    state = extract_conversation_state(prompt)

    if state is None or state.stage not in ("questionnaire_sent", "followup_sent"):
        anomaly, steps = parse_cgm_event(prompt, clients.llm_client)
        return {"response": format_questionnaire_prompt(anomaly), "steps": steps}

    # The marker is client-held and comes back unvalidated on turns 2 and 3, so
    # re-validate the anomaly it carries before it reaches retrieval (where an
    # unexpected direction would otherwise raise a bare KeyError).
    if not _valid_anomaly_dict(state.anomaly):
        raise PipelineError("conversation state carries an invalid anomaly")

    if state.stage == "questionnaire_sent":
        answers, notes = parse_answers(state.reply_text)
        context = _retrieve_context(state.anomaly, answers, clients)
        result, react_step = run_react_agent(state.anomaly, answers, notes, context, clients.llm_client)

        if result.get("need_more_info"):
            followup_question = result.get("followup_question")
            if not isinstance(followup_question, str) or not followup_question.strip():
                raise PipelineError(
                    "ReAct Agent requested a follow-up but did not provide a question"
                )
            marker = build_marker(
                "followup_sent", anomaly=state.anomaly, answers=answers, notes=notes,
                followup_question=followup_question,
            )
            return {"response": f"{followup_question}\n\n{marker}", "steps": [react_step]}

        return _finalize(state.anomaly, answers, result.get("findings") or [], clients, [react_step])

    # state.stage == "followup_sent"
    followup_answer = state.reply_text
    answers = state.answers or {}
    context = _retrieve_context(state.anomaly, answers, clients)
    result, react_step = run_react_agent(
        state.anomaly, answers, state.notes, context, clients.llm_client,
        followup={"question": state.followup_question, "answer": followup_answer},
        allow_followup=False,
    )
    return _finalize(state.anomaly, answers, result.get("findings") or [], clients, [react_step])
