"""Structured, single-line logging without sensitive payload fields."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Final

_SAFE_EXTRA_FIELDS: Final = (
    "event",
    "run_id",
    "listing_id",
    "stage",
    "recruiting_year",
)


class JsonFormatter(logging.Formatter):
    """Format one JSON object per record for bounded container logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field_name in _SAFE_EXTRA_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def configure_logging(log_level: str) -> None:
    """Configure the root logger with one structured stderr handler."""
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)
