"""Portable single-run lock behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_interner.run_lock import RunAlreadyActiveError, RunLock

pytestmark = [pytest.mark.unit, pytest.mark.portability]


def test_stale_lock_file_does_not_block_a_new_run(tmp_path: Path) -> None:
    lock_path = tmp_path / "run.lock"
    lock_path.write_bytes(b"0")

    with RunLock(lock_path):
        assert lock_path.is_file()


def test_second_owner_cannot_overlap_the_active_run(tmp_path: Path) -> None:
    first = RunLock(tmp_path / "run.lock")
    second = RunLock(tmp_path / "run.lock")
    first.acquire()
    try:
        with pytest.raises(RunAlreadyActiveError):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_one_lock_instance_cannot_be_acquired_twice(tmp_path: Path) -> None:
    lock = RunLock(tmp_path / "run.lock")
    lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="already acquired"):
            lock.acquire()
    finally:
        lock.release()
