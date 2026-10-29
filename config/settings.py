"""Application settings loaded from environment variables and .env file."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = PROJECT_ROOT / ".env"

# Ensure .env is loaded
load_dotenv(DOTENV_PATH, override=False)


class Settings(BaseModel):
    """Configuration settings for LLM, database, and observability."""

    # Project directories
    project_root: Path = PROJECT_ROOT
    db_path: Path = PROJECT_ROOT / "data" / "processed" / "companies.db"
    processed_csv_path: Path = PROJECT_ROOT / "data" / "processed" / "tracxn.csv"

    # LLM Settings (OpenAI-compatible)
    llm_base_url: str = Field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    )
    llm_api_key: str = Field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "")
    )
    primary_model: str = Field(
        default_factory=lambda: os.getenv("PRIMARY_MODEL", "meta/llama-3.3-70b-instruct")
    )
    fallback_models_raw: str = Field(
        default_factory=lambda: os.getenv(
            "FALLBACK_MODELS",
            "mistralai/mistral-large-2-instruct,meta/llama-3.1-8b-instruct",
        )
    )
    llm_temperature: float = Field(
        default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.2"))
    )
    llm_max_retries: int = Field(
        default_factory=lambda: int(os.getenv("LLM_MAX_RETRIES", "1"))
    )
    llm_timeout: float = Field(
        default_factory=lambda: float(os.getenv("LLM_TIMEOUT", "45.0"))
    )

    # Observability (Langfuse)
    langfuse_public_key: str = Field(
        default_factory=lambda: os.getenv("LANGFUSE_PUBLIC_KEY", "")
    )
    langfuse_secret_key: str = Field(
        default_factory=lambda: os.getenv("LANGFUSE_SECRET_KEY", "")
    )
    langfuse_host: str = Field(
        default_factory=lambda: os.getenv("LANGFUSE_HOST", "http://localhost:3000")
    )

    @property
    def is_langfuse_configured(self) -> bool:
        """Check whether Langfuse API credentials are configured."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def fallback_models(self) -> List[str]:
        """Return list of fallback model names, stripped of whitespace."""
        if not self.fallback_models_raw:
            return []
        return [
            m.strip()
            for m in self.fallback_models_raw.split(",")
            if m.strip() and m.strip() != self.primary_model
        ]

    @property
    def all_models(self) -> List[str]:
        """Return all configured models in priority order."""
        models = [self.primary_model]
        for fallback in self.fallback_models:
            if fallback not in models:
                models.append(fallback)
        return models


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()

