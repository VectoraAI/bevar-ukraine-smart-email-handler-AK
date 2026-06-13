"""Centralized LLM client factory — single point of access to Claude via AWS Bedrock."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from anthropic import AnthropicBedrock

from src.config.logging import get_logger
from src.config.settings import get_settings

logger = get_logger(module="llm_client")


@lru_cache(maxsize=1)
def get_bedrock_client() -> AnthropicBedrock:
    """Create and cache a Bedrock-backed Anthropic client.

    Authentication is handled by AWS credentials chain:
    - Locally: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from .env
    - In production: IAM Role (no long-lived keys needed)
    """
    settings = get_settings()

    kwargs: dict[str, Any] = {
        "aws_region": settings.aws_region,
    }
    if settings.aws_access_key_id:
        kwargs["aws_access_key"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        kwargs["aws_secret_key"] = settings.aws_secret_access_key

    logger.info("bedrock_client_init", region=settings.aws_region, model=settings.bedrock_model_id)
    return AnthropicBedrock(**kwargs)


def get_model_id() -> str:
    """Return the configured Bedrock model ID."""
    return get_settings().bedrock_model_id


def is_llm_available() -> bool:
    """Check if LLM is available (AWS credentials configured)."""
    settings = get_settings()
    # On prod, IAM Role provides creds without explicit keys
    # For local dev, at least one of the keys must be set
    return bool(settings.aws_access_key_id) or settings.app_env == "production"
