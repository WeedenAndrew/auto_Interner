"""Container heartbeat health contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from auto_interner.healthcheck import heartbeat_is_healthy, main

pytestmark = [pytest.mark.unit, pytest.mark.observability]

NOW = datetime(2027, 1, 2, 3, 4, tzinfo=UTC)


def _write(path: Path, *, status: str = "idle", timestamp: datetime = NOW) -> None:
    path.write_text(
        json.dumps(
            {"run_id": "fictional-run", "status": status, "timestamp": timestamp.isoformat()}
        ),
        encoding="utf-8",
    )


def test_recent_idle_and_running_heartbeats_are_healthy(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat.json"
    _write(path)
    assert heartbeat_is_healthy(path, now=NOW, max_age_seconds=100)

    _write(path, status="running", timestamp=NOW - timedelta(seconds=99))
    assert heartbeat_is_healthy(path, now=NOW, max_age_seconds=100)


@pytest.mark.parametrize("status", ["failed", "unknown", ""])
def test_failed_or_unknown_status_is_unhealthy(tmp_path: Path, status: str) -> None:
    path = tmp_path / "heartbeat.json"
    _write(path, status=status)

    assert not heartbeat_is_healthy(path, now=NOW, max_age_seconds=100)


def test_missing_stale_future_naive_and_oversized_heartbeats_fail(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat.json"
    assert not heartbeat_is_healthy(path, now=NOW, max_age_seconds=100)

    _write(path, timestamp=NOW - timedelta(seconds=101))
    assert not heartbeat_is_healthy(path, now=NOW, max_age_seconds=100)

    _write(path, timestamp=NOW + timedelta(seconds=61))
    assert not heartbeat_is_healthy(path, now=NOW, max_age_seconds=100)

    path.write_text(
        json.dumps({"status": "idle", "timestamp": "2027-01-02T03:04:00"}),
        encoding="utf-8",
    )
    assert not heartbeat_is_healthy(path, now=NOW, max_age_seconds=100)

    path.write_bytes(b"x" * 16_385)
    assert not heartbeat_is_healthy(path, now=NOW, max_age_seconds=100)


@pytest.mark.parametrize("content", ["not json", "[]", "{}", '{"status":"idle"}'])
def test_malformed_heartbeat_fails_closed(tmp_path: Path, content: str) -> None:
    path = tmp_path / "heartbeat.json"
    path.write_text(content, encoding="utf-8")

    assert not heartbeat_is_healthy(path, now=NOW, max_age_seconds=100)


def test_healthcheck_main_uses_environment_without_printing_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "heartbeat.json"
    _write(path, timestamp=datetime.now(UTC))
    monkeypatch.setenv("HEARTBEAT_PATH", str(path))
    monkeypatch.setenv("HEALTHCHECK_MAX_AGE_SECONDS", "100")

    assert main() == 0

    monkeypatch.setenv("HEALTHCHECK_MAX_AGE_SECONDS", "invalid")
    assert main() == 1


def test_healthcheck_rejects_invalid_limits(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat.json"
    _write(path)

    assert not heartbeat_is_healthy(path, now=NOW, max_age_seconds=0)
    assert not heartbeat_is_healthy(
        path,
        now=datetime(2027, 1, 2, 3, 4),
        max_age_seconds=100,
    )
