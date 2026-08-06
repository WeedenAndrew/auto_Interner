"""Hardened Git snapshot acquisition and cache behavior."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from auto_interner.git_source import (
    GitCommandFailure,
    GitSnapshotLoader,
    SubprocessGitRunner,
)
from auto_interner.source import SnapshotRetrievalError

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.security]

_COMMIT = "a" * 40
_REPOSITORY = "https://github.com/SimplifyJobs/Summer2027-Internships.git"


def _body() -> bytes:
    return json.dumps(
        [
            {
                "id": "fixture-one",
                "company_name": "Fictional Systems",
                "title": "Software Intern",
                "url": "https://example.invalid/jobs/fixture-one",
                "locations": ["Denver, CO"],
                "active": True,
            }
        ]
    ).encode()


class FakeRunner:
    def __init__(self, body: bytes, *, commit: str = _COMMIT) -> None:
        self.body = body
        self.commit = commit
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float,
        max_stdout_bytes: int,
    ) -> bytes:
        assert timeout_seconds == 30
        self.calls.append(tuple(arguments))
        if "rev-parse" in arguments:
            return f"{self.commit}\n".encode()
        if "cat-file" in arguments and "-s" in arguments:
            return f"{len(self.body)}\n".encode()
        if "cat-file" in arguments and "blob" in arguments:
            assert max_stdout_bytes >= len(self.body)
            return self.body
        return b""


def _loader(
    tmp_path: Path, runner: FakeRunner, *, max_bytes: int = 1024 * 1024
) -> GitSnapshotLoader:
    cache_dir = tmp_path / "source-cache" / "summer-2027.git"
    cache_dir.mkdir(parents=True)
    return GitSnapshotLoader(
        repository_url=_REPOSITORY,
        branch_ref="refs/heads/dev",
        snapshot_path=".github/scripts/listings.json",
        cache_dir=cache_dir,
        timeout_seconds=30,
        max_snapshot_bytes=max_bytes,
        runner=runner,
    )


def test_git_snapshot_fetches_a_fixed_ref_and_reads_the_blob_without_checkout(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(_body())
    loader = _loader(tmp_path, runner)

    download = loader.download()

    assert download.snapshot.listings[0].id == "fixture-one"
    assert download.source_version == _COMMIT
    assert download.changed_since_last_success is True
    fetch_call = next(call for call in runner.calls if "fetch" in call)
    assert "--depth=1" in fetch_call
    assert "--no-tags" in fetch_call
    assert _REPOSITORY in fetch_call
    assert "+refs/heads/dev:refs/auto-interner/snapshot" in fetch_call
    assert all("checkout" not in call for call in runner.calls)


def test_commit_remains_changed_until_a_successful_scan_marks_it_processed(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(_body())
    loader = _loader(tmp_path, runner)

    first = loader.download()
    assert first.changed_since_last_success is True
    loader.mark_processed(_COMMIT)

    second = loader.download()

    assert second.changed_since_last_success is False


def test_polling_path_skips_blob_read_when_commit_was_processed(tmp_path: Path) -> None:
    runner = FakeRunner(_body())
    loader = _loader(tmp_path, runner)
    loader.mark_processed(_COMMIT)

    call_offset = len(runner.calls)
    download = loader.download_if_changed()

    assert download is None
    poll_calls = runner.calls[call_offset:]
    assert any("fetch" in call for call in poll_calls)
    assert not any("cat-file" in call for call in poll_calls)


def test_snapshot_size_is_checked_before_blob_output_is_requested(tmp_path: Path) -> None:
    runner = FakeRunner(b"x" * 200)
    loader = _loader(tmp_path, runner, max_bytes=100)

    with pytest.raises(SnapshotRetrievalError, match="size limit") as captured:
        loader.download()

    assert captured.value.retryable is False
    assert not any("blob" in call for call in runner.calls)


@pytest.mark.parametrize(
    "repository_url",
    [
        "http://github.com/SimplifyJobs/Summer2027-Internships.git",
        "https://github.example/SimplifyJobs/Summer2027-Internships.git",
        "https://github.com/OtherOwner/Summer2027-Internships.git",
        "https://github.com/SimplifyJobs/Summer2027-Internships",
        "https://user:secret@github.com/SimplifyJobs/Summer2027-Internships.git",
    ],
)
def test_repository_allowlist_rejects_unsafe_or_ambiguous_urls(
    tmp_path: Path, repository_url: str
) -> None:
    with pytest.raises(ValueError, match="exact HTTPS SimplifyJobs"):
        GitSnapshotLoader(
            repository_url=repository_url,
            branch_ref="refs/heads/dev",
            snapshot_path=".github/scripts/listings.json",
            cache_dir=tmp_path / "cache.git",
            timeout_seconds=30,
        )


@pytest.mark.parametrize(
    "branch_ref", ["dev", "refs/heads/../main", "refs/heads/.hidden", "refs/tags/dev"]
)
def test_branch_ref_must_be_a_safe_fully_qualified_branch(tmp_path: Path, branch_ref: str) -> None:
    with pytest.raises(ValueError, match="branch ref"):
        GitSnapshotLoader(
            repository_url=_REPOSITORY,
            branch_ref=branch_ref,
            snapshot_path=".github/scripts/listings.json",
            cache_dir=tmp_path / "cache.git",
            timeout_seconds=30,
        )


@pytest.mark.parametrize("snapshot_path", [".", "../listings.json", "/listings.json", "a\\b.json"])
def test_snapshot_path_must_stay_relative_and_normalized(
    tmp_path: Path, snapshot_path: str
) -> None:
    with pytest.raises(ValueError, match="normalized relative"):
        GitSnapshotLoader(
            repository_url=_REPOSITORY,
            branch_ref="refs/heads/dev",
            snapshot_path=snapshot_path,
            cache_dir=tmp_path / "cache.git",
            timeout_seconds=30,
        )


def test_git_command_failure_keeps_retry_classification(tmp_path: Path) -> None:
    class FailingRunner:
        def run(
            self,
            arguments: Sequence[str],
            *,
            timeout_seconds: float,
            max_stdout_bytes: int,
        ) -> bytes:
            del arguments, timeout_seconds, max_stdout_bytes
            raise GitCommandFailure("Git operation timed out", retryable=True)

    cache_dir = tmp_path / "cache.git"
    cache_dir.mkdir()
    loader = GitSnapshotLoader(
        repository_url=_REPOSITORY,
        branch_ref="refs/heads/dev",
        snapshot_path=".github/scripts/listings.json",
        cache_dir=cache_dir,
        timeout_seconds=30,
        runner=FailingRunner(),
    )

    with pytest.raises(SnapshotRetrievalError, match="timed out") as captured:
        loader.download()

    assert captured.value.retryable is True


def test_subprocess_runner_applies_protocol_redirect_prompt_and_shell_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = tuple(command)
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    output = SubprocessGitRunner().run(("version",), timeout_seconds=5, max_stdout_bytes=10)

    command = cast(tuple[str, ...], captured["command"])
    environment = cast(Mapping[str, str], captured["env"])
    assert output == b"ok"
    assert "protocol.allow=never" in command
    assert "protocol.https.allow=always" in command
    assert "http.followRedirects=false" in command
    assert "http.sslVerify=true" in command
    assert "credential.helper=" in command
    assert captured["shell"] is False
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
