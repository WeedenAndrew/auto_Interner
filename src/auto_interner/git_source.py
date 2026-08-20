"""Hardened Git transport for versioned listing snapshots."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from hashlib import sha256
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol, cast
from urllib.parse import urlparse

from auto_interner.source import (
    SnapshotDownload,
    SnapshotFormatError,
    SnapshotRetrievalError,
    parse_snapshot_json,
)

_MAX_COMMAND_DIAGNOSTICS = 64 * 1024
_SOURCE_REF = "refs/auto-interner/snapshot"
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_BRANCH_PATTERN = re.compile(r"refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")
_REPOSITORY_PATH_PATTERN = re.compile(r"/SimplifyJobs/Summer[0-9]{4}-Internships\.git\Z")


class GitCommandFailure(RuntimeError):
    """Sanitized failure from the constrained Git subprocess boundary."""

    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


class GitRunner(Protocol):
    """Injectable command boundary used by the Git snapshot loader."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float,
        max_stdout_bytes: int,
    ) -> bytes:
        """Run one constrained Git operation and return bounded standard output."""


class _FcntlModule(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, descriptor: int, operation: int) -> None:
        """Apply or release an advisory file lock."""


class SubprocessGitRunner:
    """Invoke Git without a shell, prompts, redirects, hooks, or alternate protocols."""

    _CONFIGURATION = (
        "protocol.allow=never",
        "protocol.https.allow=always",
        "http.followRedirects=false",
        "http.proxy=",
        "http.sslVerify=true",
        "credential.helper=",
        "fetch.fsckObjects=true",
        "transfer.fsckObjects=true",
    )

    def __init__(self, executable: str = "git") -> None:
        self._executable = executable

    def _command(self, arguments: Sequence[str]) -> tuple[str, ...]:
        command = [self._executable]
        for setting in self._CONFIGURATION:
            command.extend(("-c", setting))
        if os.name == "nt":
            command.extend(("-c", "http.sslBackend=openssl"))
        command.extend(("-c", f"core.hooksPath={os.devnull}"))
        command.extend(arguments)
        return tuple(command)

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = {
            name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")
        }
        environment.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_PROTOCOL_FROM_USER": "0",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        return environment

    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float,
        max_stdout_bytes: int,
    ) -> bytes:
        """Run Git with fixed security controls and sanitized failures."""
        try:
            completed = subprocess.run(
                self._command(arguments),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
                env=self._environment(),
                shell=False,
            )
        except FileNotFoundError as exc:
            raise GitCommandFailure("Git executable is unavailable", retryable=False) from exc
        except subprocess.TimeoutExpired as exc:
            raise GitCommandFailure("Git operation timed out", retryable=True) from exc
        except OSError as exc:
            raise GitCommandFailure("Git process could not be started", retryable=True) from exc

        if len(completed.stdout) > max_stdout_bytes:
            raise GitCommandFailure("Git output exceeded its configured limit", retryable=False)
        if len(completed.stderr) > _MAX_COMMAND_DIAGNOSTICS:
            raise GitCommandFailure(
                "Git diagnostics exceeded their configured limit", retryable=False
            )
        if completed.returncode != 0:
            raise GitCommandFailure("Git operation failed", retryable=True)
        return completed.stdout


def _validate_repository_url(repository_url: str) -> None:
    parsed = urlparse(repository_url)
    if (
        repository_url != repository_url.strip()
        or any(ord(character) < 32 for character in repository_url)
        or parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not _REPOSITORY_PATH_PATTERN.fullmatch(parsed.path)
    ):
        raise ValueError(
            "Git source must be an exact HTTPS SimplifyJobs Summer internship repository URL"
        )


def _validate_branch_ref(branch_ref: str) -> None:
    forbidden = ("..", "@{", "//", "\\")
    components = branch_ref.split("/")
    if (
        not _BRANCH_PATTERN.fullmatch(branch_ref)
        or any(value in branch_ref for value in forbidden)
        or branch_ref.endswith(("/", ".", ".lock"))
        or any(component.startswith(".") or component.endswith(".lock") for component in components)
    ):
        raise ValueError("Git source ref must be a valid fully qualified branch ref")


def _validate_snapshot_path(snapshot_path: str) -> None:
    path = PurePosixPath(snapshot_path)
    if (
        not snapshot_path
        or snapshot_path == "."
        or len(snapshot_path) > 500
        or path.is_absolute()
        or snapshot_path != path.as_posix()
        or "\\" in snapshot_path
        or ".." in path.parts
        or ":" in snapshot_path
        or any(ord(character) < 32 for character in snapshot_path)
    ):
        raise ValueError("Git snapshot path must be a normalized relative repository path")


def _lock_file(handle: BinaryIO) -> None:
    # `sys.platform`, not `os.name`. Both are correct at runtime, but mypy only
    # narrows on sys.platform, and typeshed hides every msvcrt attribute behind
    # `sys.platform == "win32"`. Written as os.name, the Linux leg of the CI
    # matrix analyses this branch anyway and fails with "Module has no attribute
    # locking". Changing it back reintroduces a failure Windows never sees.
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        if not handle.read(1):
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    fcntl = cast(_FcntlModule, import_module("fcntl"))
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":  # see _lock_file
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    fcntl = cast(_FcntlModule, import_module("fcntl"))
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _exclusive_cache_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        try:
            _lock_file(handle)
        except OSError as exc:
            raise SnapshotRetrievalError(
                "Git source cache is already in use", retryable=True
            ) from exc
        try:
            yield
        finally:
            _unlock_file(handle)


class GitSnapshotLoader:
    """Fetch and parse one immutable snapshot from a private bare Git cache."""

    def __init__(
        self,
        *,
        repository_url: str,
        branch_ref: str,
        snapshot_path: str,
        cache_dir: Path,
        timeout_seconds: float,
        max_snapshot_bytes: int = 20 * 1024 * 1024,
        runner: GitRunner | None = None,
    ) -> None:
        _validate_repository_url(repository_url)
        _validate_branch_ref(branch_ref)
        _validate_snapshot_path(snapshot_path)
        if timeout_seconds <= 0:
            raise ValueError("Git timeout must be positive")
        if max_snapshot_bytes <= 0:
            raise ValueError("Git snapshot size limit must be positive")
        self._repository_url = repository_url
        self._branch_ref = branch_ref
        self._snapshot_path = snapshot_path
        self._cache_dir = cache_dir
        self._timeout_seconds = timeout_seconds
        self._max_snapshot_bytes = max_snapshot_bytes
        self._runner = SubprocessGitRunner() if runner is None else runner
        self._lock_path = cache_dir.with_suffix(f"{cache_dir.suffix}.lock")
        self._processed_marker = cache_dir.with_suffix(f"{cache_dir.suffix}.processed")

    def _run(self, arguments: Sequence[str], *, max_stdout_bytes: int) -> bytes:
        try:
            return self._runner.run(
                arguments,
                timeout_seconds=self._timeout_seconds,
                max_stdout_bytes=max_stdout_bytes,
            )
        except GitCommandFailure as exc:
            raise SnapshotRetrievalError(exc.reason, retryable=exc.retryable) from exc

    def _ensure_cache(self) -> None:
        if self._cache_dir.exists():
            if self._cache_dir.is_symlink() or not self._cache_dir.is_dir():
                raise SnapshotRetrievalError(
                    "Git source cache path is not a directory", retryable=False
                )
            return
        self._cache_dir.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            ("init", "--bare", str(self._cache_dir)),
            max_stdout_bytes=_MAX_COMMAND_DIAGNOSTICS,
        )

    def _last_processed_commit(self) -> str | None:
        if not self._processed_marker.exists():
            return None
        try:
            commit = self._processed_marker.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise SnapshotRetrievalError(
                "Git processed-commit marker could not be read", retryable=False
            ) from exc
        if not _COMMIT_PATTERN.fullmatch(commit):
            raise SnapshotRetrievalError("Git processed-commit marker is invalid", retryable=False)
        return commit

    def _fetch_commit(self) -> str:
        self._ensure_cache()
        refspec = f"+{self._branch_ref}:{_SOURCE_REF}"
        self._run(
            (
                "--git-dir",
                str(self._cache_dir),
                "fetch",
                "--quiet",
                "--no-tags",
                "--depth=1",
                self._repository_url,
                refspec,
            ),
            max_stdout_bytes=_MAX_COMMAND_DIAGNOSTICS,
        )
        raw_commit = self._run(
            ("--git-dir", str(self._cache_dir), "rev-parse", "--verify", _SOURCE_REF),
            max_stdout_bytes=128,
        )
        try:
            commit = raw_commit.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise SnapshotRetrievalError(
                "Git returned an invalid source commit", retryable=False
            ) from exc
        if not _COMMIT_PATTERN.fullmatch(commit):
            raise SnapshotRetrievalError("Git returned an invalid source commit", retryable=False)
        return commit

    def _read_snapshot(self, commit: str, last_processed_commit: str | None) -> SnapshotDownload:
        object_name = f"{commit}:{self._snapshot_path}"
        raw_size = self._run(
            ("--git-dir", str(self._cache_dir), "cat-file", "-s", object_name),
            max_stdout_bytes=64,
        )
        try:
            content_length = int(raw_size.decode("ascii").strip())
        except (UnicodeDecodeError, ValueError) as exc:
            raise SnapshotRetrievalError(
                "Git returned an invalid snapshot size", retryable=False
            ) from exc
        if content_length < 0 or content_length > self._max_snapshot_bytes:
            raise SnapshotRetrievalError(
                "Git snapshot exceeds its configured size limit", retryable=False
            )

        body = self._run(
            ("--git-dir", str(self._cache_dir), "cat-file", "blob", object_name),
            max_stdout_bytes=self._max_snapshot_bytes,
        )
        if len(body) != content_length:
            raise SnapshotRetrievalError(
                "Git snapshot size did not match its object metadata", retryable=False
            )
        try:
            document = body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SnapshotRetrievalError(
                "Git snapshot is not valid UTF-8", retryable=False
            ) from exc
        try:
            snapshot = parse_snapshot_json(document)
        except SnapshotFormatError as exc:
            raise SnapshotRetrievalError(str(exc), retryable=False) from exc

        return SnapshotDownload(
            snapshot=snapshot,
            content_hash=sha256(body).hexdigest(),
            content_length=content_length,
            source_version=commit,
            changed_since_last_success=commit != last_processed_commit,
        )

    def download(self) -> SnapshotDownload:
        """Fetch and validate the branch-tip snapshot even when it is unchanged."""
        with _exclusive_cache_lock(self._lock_path):
            commit = self._fetch_commit()
            return self._read_snapshot(commit, self._last_processed_commit())

    def download_if_changed(self) -> SnapshotDownload | None:
        """Fetch the branch tip and skip blob parsing when it was already processed."""
        with _exclusive_cache_lock(self._lock_path):
            commit = self._fetch_commit()
            last_processed_commit = self._last_processed_commit()
            if commit == last_processed_commit:
                return None
            return self._read_snapshot(commit, last_processed_commit)

    def mark_processed(self, commit: str) -> None:
        """Atomically record a commit only after its complete scan succeeds."""
        if not _COMMIT_PATTERN.fullmatch(commit):
            raise ValueError("processed Git commit must be a complete hexadecimal object ID")
        with _exclusive_cache_lock(self._lock_path):
            self._processed_marker.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self._processed_marker.name}.",
                dir=self._processed_marker.parent,
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
                    handle.write(f"{commit}\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, self._processed_marker)
            finally:
                temporary_path.unlink(missing_ok=True)
