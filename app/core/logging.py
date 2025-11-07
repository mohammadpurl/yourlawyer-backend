"""Centralized logging configuration for the backend service."""

from __future__ import annotations

import logging
import logging.config
import os
from typing import Any, Dict


DEFAULT_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def _build_handlers() -> Dict[str, Dict[str, Any]]:
    log_format = os.getenv("LOG_FORMAT", "plain").lower()
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    console_handler: Dict[str, Any] = {
        "class": "logging.StreamHandler",
        "formatter": "json" if log_format == "json" else "standard",
        "level": level,
    }

    return {"console": console_handler}


def _build_formatters() -> Dict[str, Dict[str, Any]]:
    formatters: Dict[str, Dict[str, Any]] = {
        "standard": {
            "format": os.getenv("LOG_FORMAT_STRING", DEFAULT_FORMAT),
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        }
    }

    if os.getenv("LOG_FORMAT", "plain").lower() == "json":
        try:
            from pythonjsonlogger import jsonlogger  # type: ignore

            formatters["json"] = {
                "()": jsonlogger.JsonFormatter,
                "fmt": os.getenv("LOG_JSON_FIELDS", DEFAULT_FORMAT),
            }
        except ImportError:
            # Fallback to standard formatter if package is missing
            formatters["json"] = formatters["standard"]

    return formatters


def _build_loggers(level: str) -> Dict[str, Dict[str, Any]]:
    return {
        "": {  # root logger
            "handlers": ["console"],
            "level": level,
        },
        "uvicorn": {
            "handlers": ["console"],
            "level": level,
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["console"],
            "level": level,
            "propagate": False,
        },
    }


def configure_logging() -> None:
    """Configure application logging based on environment variables."""

    level = os.getenv("LOG_LEVEL", "INFO").upper()

    logging_config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": _build_formatters(),
        "handlers": _build_handlers(),
        "loggers": _build_loggers(level),
    }

    logging.config.dictConfig(logging_config)

    logging.getLogger(__name__).debug("Logging configured", extra={"level": level})

