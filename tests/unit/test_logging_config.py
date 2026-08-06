"""Structured logging safety checks."""

from __future__ import annotations

import json
import logging

import pytest

from auto_interner.logging_config import JsonFormatter

pytestmark = [pytest.mark.unit, pytest.mark.observability, pytest.mark.security]


def test_json_formatter_emits_one_parseable_line() -> None:
    """Control characters remain inside JSON and cannot forge a log entry."""
    record = logging.LogRecord(
        name="auto_interner.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="first line\nforged line",
        args=(),
        exc_info=None,
    )
    record.run_id = "run-123"

    rendered = JsonFormatter().format(record)
    payload = json.loads(rendered)

    assert "\n" not in rendered
    assert payload["message"] == "first line\nforged line"
    assert payload["run_id"] == "run-123"
