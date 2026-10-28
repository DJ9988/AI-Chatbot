"""Unit tests for configuration and LLM provider."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure project root is in sys.path when running script directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings, get_settings
from config.provider import create_single_chat_model, get_chat_model
from langchain_openai import ChatOpenAI


def test_settings_default_values():
    """Verify default settings values when env vars are not set."""
    settings = Settings()
    assert settings.llm_base_url == "https://integrate.api.nvidia.com/v1"
    assert "llama-3.3-70b-instruct" in settings.primary_model
    assert len(settings.fallback_models) >= 1
    assert settings.primary_model not in settings.fallback_models
    assert settings.all_models[0] == settings.primary_model


def test_settings_custom_env():
    """Verify custom environment values are parsed properly."""
    custom = Settings(
        llm_base_url="https://api.openai.com/v1",
        llm_api_key="test-key-123",
        primary_model="model-a",
        fallback_models_raw="model-b, model-c, model-a",
        llm_temperature=0.5,
        llm_max_retries=2,
    )
    assert custom.llm_base_url == "https://api.openai.com/v1"
    assert custom.llm_api_key == "test-key-123"
    assert custom.primary_model == "model-a"
    # model-a should be stripped from fallbacks since it is primary
    assert custom.fallback_models == ["model-b", "model-c"]
    assert custom.all_models == ["model-a", "model-b", "model-c"]


def test_create_single_chat_model():
    """Verify single ChatOpenAI client initialization."""
    settings = Settings(
        llm_base_url="https://test.endpoint/v1",
        llm_api_key="dummy-key",
        primary_model="test-model",
    )
    model = create_single_chat_model("test-model", settings=settings)
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "test-model"
    assert str(model.openai_api_base).rstrip("/") == "https://test.endpoint/v1"


def test_get_chat_model_with_fallbacks():
    """Verify fallback chain construction in LangChain."""
    settings = Settings(
        llm_base_url="https://test.endpoint/v1",
        llm_api_key="dummy-key",
        primary_model="primary-model",
        fallback_models_raw="fallback-1,fallback-2",
    )
    model = get_chat_model(settings=settings)
    # When with_fallbacks is called, LangChain returns a RunnableWithFallbacks
    assert hasattr(model, "fallbacks")
    assert len(model.fallbacks) == 2


def test_get_chat_model_no_fallbacks():
    """Verify single model returned when no fallbacks configured."""
    settings = Settings(
        llm_base_url="https://test.endpoint/v1",
        llm_api_key="dummy-key",
        primary_model="only-model",
        fallback_models_raw="",
    )
    model = get_chat_model(settings=settings)
    assert isinstance(model, ChatOpenAI)
    assert not hasattr(model, "fallbacks")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__]))


