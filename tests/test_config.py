import pytest
import config


def test_require_raises_when_value_missing():
    with pytest.raises(RuntimeError, match="FOO_VAR"):
        config.require(None, "FOO_VAR")


def test_require_raises_when_value_empty_string():
    with pytest.raises(RuntimeError, match="FOO_VAR"):
        config.require("", "FOO_VAR")


def test_require_returns_value_when_present():
    assert config.require("abc", "FOO_VAR") == "abc"


def test_model_constants_are_set():
    assert config.TEXT_MODEL == "MB5R2CF-azure/gpt-5.4-mini"
    assert config.EMBED_MODEL == "MB5R2CF-azure/text-embedding-3-small"
