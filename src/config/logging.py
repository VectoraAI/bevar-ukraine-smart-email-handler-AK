from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from src.config.settings import get_settings


def setup_logging() -> None:
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer() if settings.is_production else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=log_level, format="%(message)s", stream=sys.stdout, force=True)
    for noisy in ("boto3", "botocore", "urllib3", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(**kwargs: Any) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(**kwargs)  # type: ignore[return-value]
