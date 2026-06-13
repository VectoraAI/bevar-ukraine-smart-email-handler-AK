from __future__ import annotations

import re

from src.config.logging import get_logger

logger = get_logger(module="privacy")

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_PATTERN = re.compile(r"\+?\d[\d\s\-()]{7,}\d")
_CPR_PATTERN = re.compile(r"\b\d{6}-?\d{4}\b")


def mask_pii(text: str) -> str:
    """Mask PII in text for safe logging."""
    text = _EMAIL_PATTERN.sub("[EMAIL]", text)
    text = _PHONE_PATTERN.sub("[PHONE]", text)
    text = _CPR_PATTERN.sub("[ID-NUMBER]", text)
    return text


def safe_log_query(query: str) -> str:
    """Return a PII-masked version of a query for logging."""
    return mask_pii(query)
