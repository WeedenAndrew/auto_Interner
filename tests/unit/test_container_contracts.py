"""Static security and portability contracts for public container files."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.portability]

ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_is_multiarch_nonroot_and_contains_required_runtime() -> None:
    content = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "python:3.12.13-slim-bookworm" in content
    assert "chromium" in content and "chromium-driver" in content
    assert "git" in content and "tini" in content
    assert "USER ${APP_UID}:${APP_GID}" in content
    assert 'ENTRYPOINT ["/usr/bin/tini", "--", "auto-interner"]' in content
    assert "auto_interner.healthcheck" in content
    assert "ANTHROPIC_API_KEY" not in content
    assert "COPY ." not in content


def test_compose_worker_has_durable_mounts_and_bounded_isolation() -> None:
    content = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    required = (
        "restart: unless-stopped",
        "stop_signal: SIGTERM",
        "AUTO_INTERNER_DATA_DIR",
        "AUTO_INTERNER_STATE_DIR",
        "create_host_path: false",
        "read_only: true",
        "no-new-privileges:true",
        "cap_drop:",
        "pids_limit: 256",
        "AUTO_INTERNER_MEMORY_LIMIT:-1536m",
        "AUTO_INTERNER_MEMORY_RESERVATION:-256m",
        "AUTO_INTERNER_CPUS:-2.0",
        'max-size: "10m"',
        'max-file: "3"',
        "auto_interner.healthcheck",
    )
    assert all(value in content for value in required)
    assert "ports:" not in content
    assert content.count("network_mode: none") == 2
    assert "\t" not in content


def test_build_context_excludes_private_runtime_and_keeps_only_fictional_docx() -> None:
    content = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env" in content
    assert "*.egg-info" in content
    assert "runtime/*" in content
    assert "*.docx" in content
    assert "!src/auto_interner/demo_data/*.docx" in content
    assert "browser-profile" in content

    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    secret_line = next(
        line for line in example.splitlines() if line.startswith("ANTHROPIC_API_KEY=")
    )
    assert secret_line == "ANTHROPIC_API_KEY="
