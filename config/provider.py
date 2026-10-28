"""LLM provider factory supporting OpenAI-compatible endpoints with fallback models."""

from __future__ import annotations

import logging
from typing import List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def create_single_chat_model(
    model_name: str,
    settings: Optional[Settings] = None,
    temperature: Optional[float] = None,
) -> ChatOpenAI:
    """Create a single ChatOpenAI client pointing to the configured base URL."""
    cfg = settings or get_settings()
    api_key = cfg.llm_api_key or "placeholder_key"

    return ChatOpenAI(
        model=model_name,
        base_url=cfg.llm_base_url,
        api_key=api_key,
        temperature=cfg.llm_temperature if temperature is None else temperature,
        max_retries=cfg.llm_max_retries,
        timeout=cfg.llm_timeout,
    )


def get_chat_model(
    settings: Optional[Settings] = None,
    temperature: Optional[float] = None,
) -> BaseChatModel:
    """Return the primary chat model configured with automatic fallback models.

    If primary model invocation encounters a rate limit (HTTP 429), server error (5xx),
    or connection timeout, LangChain automatically cascades to the specified fallback models.
    """
    cfg = settings or get_settings()

    primary_model = create_single_chat_model(
        model_name=cfg.primary_model,
        settings=cfg,
        temperature=temperature,
    )

    fallback_names = cfg.fallback_models
    if not fallback_names:
        return primary_model

    fallback_models: List[BaseChatModel] = [
        create_single_chat_model(
            model_name=name,
            settings=cfg,
            temperature=temperature,
        )
        for name in fallback_names
    ]

    logger.info(
        "Configured primary model %s with %d fallback(s): %s",
        cfg.primary_model,
        len(fallback_models),
        fallback_names,
    )

    return primary_model.with_fallbacks(fallback_models)

