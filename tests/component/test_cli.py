"""Phase 0 command-line diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_interner.cli import main
from auto_interner.sources import SnapshotDownload, SnapshotRetrievalError, parse_snapshot_payload

pytestmark = [pytest.mark.component, pytest.mark.acceptance, pytest.mark.e2e]


def _valid_environment(tmp_path: Path) -> dict[str, str]:
    data_dir = tmp_path / "data"
    base_resume = data_dir / "2027" / "baseplate" / "base_resume.docx"
    base_resume.parent.mkdir(parents=True)
    base_resume.write_bytes(b"fictional test placeholder")
    return {
        "RECRUITING_YEAR": "2027",
        "LISTINGS_SOURCE_MODE": "http",
        "LISTINGS_URL": "https://example.com/listings.json",
        "DATA_DIR": str(data_dir),
        "STATE_DIR": str(tmp_path / "state"),
        "ANTHROPIC_MODEL": "account-model-id",
        "ANTHROPIC_API_KEY": "test-only-secret",
    }


def test_config_check_reports_safe_diagnostics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The diagnostic command validates prerequisites without leaking a key."""
    result = main(["config-check", "--require-model-key"], environment=_valid_environment(tmp_path))

    captured = capsys.readouterr()
    assert result == 0
    assert '"anthropic_api_key_configured": true' in captured.out
    assert "test-only-secret" not in captured.out
    assert "test-only-secret" not in captured.err


def test_config_check_returns_actionable_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Invalid configuration exits nonzero and names the missing settings."""
    result = main(["config-check"], environment={"DATA_DIR": str(tmp_path)})

    captured = capsys.readouterr()
    assert result == 2
    assert "ANTHROPIC_MODEL" in captured.err


def test_demo_runs_offline_without_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bundled fictional fixtures run without a resume, key, or source URL."""
    result = main(["demo", "--state-dir", str(tmp_path / "demo-state")], environment={})

    captured = capsys.readouterr()
    assert result == 0
    assert '"processed": 4' in captured.out
    assert '"disqualified": 2' in captured.out
    assert '"fixture_fetches": 3' in captured.out
    assert captured.err == ""


def test_demo_second_run_skips_terminal_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "demo-state"

    assert main(["demo", "--state-dir", str(state_dir)], environment={}) == 0
    capsys.readouterr()
    assert main(["demo", "--state-dir", str(state_dir)], environment={}) == 0

    second = capsys.readouterr()
    assert '"skipped_seen": 2' in second.out
    assert '"processed": 2' in second.out
    assert '"fixture_fetches": 2' in second.out


def test_demo_rejects_invalid_attempt_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(
        [
            "demo",
            "--state-dir",
            str(tmp_path / "demo-state"),
            "--max-fetch-attempts",
            "0",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "max_fetch_attempts must be positive" in captured.err


def test_source_check_reports_validated_snapshot_metadata_without_body(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = parse_snapshot_payload(
        [
            {
                "id": "fixture-one",
                "company_name": "Fictional Systems",
                "title": "Software Intern",
                "url": "https://example.invalid/fixture-one",
                "locations": ["Denver, CO"],
                "active": True,
            }
        ]
    )

    def fake_download(self: object, url: str) -> SnapshotDownload:
        del self
        assert url == "https://example.com/listings.json"
        return SnapshotDownload(snapshot, "a" * 64, 123)

    monkeypatch.setattr("auto_interner.cli.RemoteSnapshotLoader.download", fake_download)

    result = main(["source-check"], environment=_valid_environment(tmp_path))

    captured = capsys.readouterr()
    assert result == 0
    assert '"accepted_records": 1' in captured.out
    assert '"content_length": 123' in captured.out
    assert '"source_mode": "http"' in captured.out
    assert "Fictional Systems" not in captured.out


def test_source_check_returns_sanitized_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_download(self: object, url: str) -> SnapshotDownload:
        del self, url
        raise SnapshotRetrievalError("request timed out", retryable=True)

    monkeypatch.setattr("auto_interner.cli.RemoteSnapshotLoader.download", fake_download)

    result = main(["source-check"], environment=_valid_environment(tmp_path))

    captured = capsys.readouterr()
    assert result == 2
    assert "Source error: request timed out" in captured.err


def test_source_check_dispatches_to_git_and_reports_commit_metadata(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _valid_environment(tmp_path)
    environment["LISTINGS_SOURCE_MODE"] = "git"
    del environment["LISTINGS_URL"]
    snapshot = parse_snapshot_payload(
        [
            {
                "id": "fixture-git",
                "company_name": "Fictional Systems",
                "title": "Software Intern",
                "url": "https://example.invalid/fixture-git",
                "locations": ["Denver, CO"],
                "active": True,
            }
        ]
    )

    def fake_download(self: object) -> SnapshotDownload:
        del self
        return SnapshotDownload(snapshot, "b" * 64, 456, "c" * 40, True)

    monkeypatch.setattr("auto_interner.cli.GitSnapshotLoader.download", fake_download)

    result = main(["source-check"], environment=environment)

    captured = capsys.readouterr()
    assert result == 0
    assert '"source_mode": "git"' in captured.out
    assert '"source_version": "cccccccccccccccccccccccccccccccccccccccc"' in captured.out
    assert '"changed_since_last_success": true' in captured.out


def test_run_once_fixture_shadow_writes_no_resume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"

    result = main(
        [
            "run-once",
            "--fixture",
            "--data-dir",
            str(data_dir),
            "--state-dir",
            str(tmp_path / "state"),
        ],
        environment={},
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["status_counts"] == {"shadow_ready": 1}
    assert output["source_checkpointed"] is False
    assert not data_dir.exists()


def test_run_once_fixture_write_uses_company_role_date_structure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"

    result = main(
        [
            "run-once",
            "--fixture",
            "--write",
            "--data-dir",
            str(data_dir),
            "--state-dir",
            str(state_dir),
        ],
        environment={},
    )

    output = json.loads(capsys.readouterr().out)
    generated = list((data_dir / "2027" / "fictional-systems").glob("*.docx"))
    assert result == 0
    assert output["status_counts"] == {"resume_generated": 1}
    assert output["source_checkpointed"] is True
    assert len(generated) == 1
    assert generated[0].name.startswith("engineering-software_")

    assert (
        main(
            [
                "run-once",
                "--fixture",
                "--write",
                "--data-dir",
                str(data_dir),
                "--state-dir",
                str(state_dir),
            ],
            environment={},
        )
        == 0
    )
    second = json.loads(capsys.readouterr().out)
    assert second["source_changed"] is False


def test_manual_review_count_does_not_require_model_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(
        ["manual-review-count", "--state-dir", str(tmp_path / "state")],
        environment={},
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {"manual_review_count": 0}


def test_live_run_rejects_write_flag_without_fixture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(["run-once", "--write"], environment=_valid_environment(tmp_path))

    assert result == 2
    assert "only accepted with --fixture" in capsys.readouterr().err


def test_run_once_help_is_readable(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["run-once", "--help"], environment={})

    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "fixture runs" in output
    assert "--fixture" in output


def test_daemon_command_uses_configured_coordinator_and_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = object()
    calls: list[tuple[object, float]] = []

    monkeypatch.setattr(
        "auto_interner.cli.build_live_coordinator",
        lambda settings: coordinator,
    )

    def fake_daemon(
        received: object,
        *,
        interval_seconds: float,
        stop_event: object,
    ) -> None:
        del stop_event
        calls.append((received, interval_seconds))

    monkeypatch.setattr("auto_interner.cli.run_daemon", fake_daemon)

    assert (
        main(
            ["daemon", "--interval-seconds", "5"],
            environment=_valid_environment(tmp_path),
        )
        == 0
    )
    assert calls == [(coordinator, 5.0)]
