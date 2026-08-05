import json
import pytest
from unittest.mock import MagicMock

import config
import llm_client
from errors import PipelineError


def _fake_chat_client(content: str):
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=content))
    ]
    return client


def test_get_llm_client_raises_when_key_missing(monkeypatch):
    monkeypatch.setattr(config, "LLMOD_API_KEY", None)
    monkeypatch.setattr(config, "LLMOD_BASE_URL", "https://example.test")
    with pytest.raises(RuntimeError, match="LLMOD_API_KEY"):
        llm_client.get_llm_client()


def test_chat_json_parses_response_and_builds_step():
    client = _fake_chat_client('{"foo": "bar"}')

    parsed, step = llm_client.chat_json(client, "CGM Event", "sys prompt", "user prompt")

    assert parsed == {"foo": "bar"}
    assert step == {
        "module": "CGM Event",
        "prompt": {"system_prompt": "sys prompt", "user_prompt": "user prompt"},
        "response": {"foo": "bar"},
    }
    client.chat.completions.create.assert_called_once()
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == config.TEXT_MODEL
    assert call_kwargs["messages"] == [
        {"role": "system", "content": "sys prompt"},
        {"role": "user", "content": "user prompt"},
    ]


def test_chat_json_raises_pipeline_error_on_invalid_json():
    client = _fake_chat_client("not valid json")
    with pytest.raises(PipelineError, match="invalid JSON"):
        llm_client.chat_json(client, "CGM Event", "sys", "user")


def test_chat_json_raises_pipeline_error_on_none_content():
    """Azure content filtering (plausible on teen-health text) returns
    message.content=None; json.loads(None) would raise an uncaught TypeError."""
    client = _fake_chat_client(None)
    with pytest.raises(PipelineError, match="CGM Event returned an empty response"):
        llm_client.chat_json(client, "CGM Event", "sys", "user")


def test_chat_json_raises_pipeline_error_on_empty_string_content():
    client = _fake_chat_client("")
    with pytest.raises(PipelineError, match="returned an empty response"):
        llm_client.chat_json(client, "CGM Event", "sys", "user")


def test_chat_json_raises_pipeline_error_on_non_object_json():
    """A JSON array/scalar parses fine but would AttributeError later at a
    .get(...) call site, far from the actual cause."""
    client = _fake_chat_client("[1, 2, 3]")
    with pytest.raises(PipelineError, match="CGM Event returned non-object JSON"):
        llm_client.chat_json(client, "CGM Event", "sys", "user")


def test_chat_json_raises_pipeline_error_on_api_failure():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("connection reset")
    with pytest.raises(PipelineError, match="CGM Event call failed"):
        llm_client.chat_json(client, "CGM Event", "sys", "user")


def test_embed_text_returns_vector():
    client = MagicMock()
    client.embeddings.create.return_value.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    vector = llm_client.embed_text(client, "some text")

    assert vector == [0.1, 0.2, 0.3]
    client.embeddings.create.assert_called_once_with(model=config.EMBED_MODEL, input="some text")


def test_embed_text_raises_pipeline_error_on_api_failure():
    client = MagicMock()
    client.embeddings.create.side_effect = RuntimeError("connection reset")
    with pytest.raises(PipelineError, match="embedding call failed"):
        llm_client.embed_text(client, "some text")
