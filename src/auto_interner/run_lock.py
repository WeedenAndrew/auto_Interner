"""Portable nonblocking process lock for the complete worker run."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO


class RunAlreadyActiveError(RuntimeError):
    """Another worker currently owns the single-run lock."""


def _lock_file(handle: BinaryIO) -> None:
    # `sys.platform`, not `os.name`. Both are correct at runtime, but mypy only
    # narrows on sys.platform, and typeshed hides every msvcrt attribute behind
    # `sys.platform == "win32"`. Written as os.name, the Linux leg of the CI
    # matrix analyses this branch anyway and fails with "Module has no attribute
    # locking". Changing it back reintroduces a failure Windows never sees.
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RunAlreadyActiveError("another Auto Interner run is active") from exc
        return
    fcntl: Any = import_module("fcntl")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise RunAlreadyActiveError("another Auto Interner run is active") from exc


def _unlock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":  # see _lock_file
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl: Any = import_module("fcntl")
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class RunLock:
    """Hold an operating-system lock while leaving a harmless stable lock file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        """Acquire immediately or raise instead of waiting for overlap."""
        if self._handle is not None:
            raise RuntimeError("run lock is already acquired by this instance")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        try:
            _lock_file(handle)
        except BaseException:
            handle.close()
            raise
        self._handle = handle

    def release(self) -> None:
        """Release the OS lock; the file may remain for reuse after crashes."""
        if self._handle is None:
            return
        try:
            _unlock_file(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> RunLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.release()
