"""Container heartbeat health check with no network or secret access."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

_HEALTHY_STATUSES = frozenset({"running", "idle"})


def heartbeat_is_healthy(
    path: Path,
    *,
    now: datetime,
    max_age_seconds: float,
) -> bool:
    """Return whether a bounded, timezone-aware heartbeat is recent and healthy."""
    if max_age_seconds <= 0 or now.tzinfo is None or now.utcoffset() is None:
        return False
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_384:
            return False
        payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or payload.get("status") not in _HEALTHY_STATUSES:
        return False
    raw_timestamp = payload.get("timestamp")
    if not isinstance(raw_timestamp, str):
        return False
    try:
        timestamp = datetime.fromisoformat(raw_timestamp)
    except ValueError:
        return False
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return False
    age_seconds = (now - timestamp.astimezone(UTC)).total_seconds()
    return -60 <= age_seconds <= max_age_seconds


def main() -> int:
    """Check the configured heartbeat and return a Docker-compatible exit code."""
    path = Path(os.environ.get("HEARTBEAT_PATH", "/app/state/heartbeat.json"))
    try:
        max_age_seconds = float(os.environ.get("HEALTHCHECK_MAX_AGE_SECONDS", "10800"))
    except ValueError:
        return 1
    healthy = heartbeat_is_healthy(
        path,
        now=datetime.now(UTC),
        max_age_seconds=max_age_seconds,
    )
    return 0 if healthy else 1


if __name__ == "__main__":  # pragma: no cover - exercised by the container
    raise SystemExit(main())
