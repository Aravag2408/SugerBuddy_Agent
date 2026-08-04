from __future__ import annotations
import json

from openai import OpenAI

import config
from errors import PipelineError


def get_llm_client() -> OpenAI:
    return OpenAI(
        api_key=config.require(config.LLMOD_API_KEY, "LLMOD_API_KEY"),
        base_url=config.require(config.LLMOD_BASE_URL, "LLMOD_BASE_URL"),
    )


def chat_json(client, module: str, system_prompt: str, user_prompt: str) -> tuple[dict, dict]:
    try:
        completion = client.chat.completions.create(
            model=config.TEXT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content
    except Exception as e:
        raise PipelineError(f"{module} call failed: {e}") from e

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PipelineError(f"{module} returned invalid JSON: {e}") from e

    step = {
        "module": module,
        "prompt": {"system_prompt": system_prompt, "user_prompt": user_prompt},
        "response": parsed,
    }
    return parsed, step


def embed_text(client, text: str) -> list[float]:
    response = client.embeddings.create(model=config.EMBED_MODEL, input=text)
    return response.data[0].embedding
