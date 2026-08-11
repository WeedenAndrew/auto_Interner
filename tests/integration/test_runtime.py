"""Phase 6 checkpoint, heartbeat, and scheduler integration cases."""

from __future__ import annotations

import json
import signal
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from auto_interner.models import (
    Listing,
    PipelineOutcome,
    PipelineRunResult,
    PipelineStatus,
)
from auto_interner.runtime import RunCoordinator, run_daemon
from auto_interner.sources import SnapshotDownload, SnapshotResult
from auto_interner.state_store import StateCorruptionError, StateStore

pytestmark = pytest.mark.integration

START = datetime(2027, 1, 2, 3, 4, tzinfo=UTC)


def _listing() -> Listing:
    return Listing(
        id="fictional-1",
        company_name="Fictional Systems",
        title="Software Intern",
        url="https://example.invalid/fictional-1",
        locations=("Denver, CO",),
        active=True,
    )


class FakeSource:
    def __init__(self, download: SnapshotDownload | None) -> None:
        self.download = download
        self.marked: list[str] = []

    def acquire(self) -> SnapshotDownload | None:
        return self.download

    def mark_processed(self, source_version: str) -> None:
        self.marked.append(source_version)


class FakePipeline:
    def __init__(self, status: PipelineStatus, store: StateStore) -> None:
        self.status = status
        self.store = store

    def run(self, listings: object) -> PipelineRunResult:
        snapshot = tuple(listings)  # type: ignore[call-overload]
        outcome = PipelineOutcome(
            listing_id=snapshot[0].id,
            status=self.status,
            summary="fictional result",
            timestamp=START,
        )
        if outcome.is_terminal:
            self.store.commit_terminal(outcome)
        return PipelineRunResult(1, 1, 0, 1, (outcome,))


def _download() -> SnapshotDownload:
    return SnapshotDownload(SnapshotResult((_listing(),), ()), "a" * 64, 100, "b" * 40, True)


def _clock() -> object:
    values = iter((START, START + timedelta(seconds=1)))
    return lambda: next(values)


def test_terminal_run_checkpoints_source_and_publishes_observability(tmp_path: Path) -> None:
    source = FakeSource(_download())
    store = StateStore(tmp_path / "state")
    coordinator = RunCoordinator(
        source=source,
        pipeline=FakePipeline(PipelineStatus.RESUME_GENERATED, store),
        state_store=store,
        clock=_clock(),  # type: ignore[arg-type]
        run_id_factory=lambda: "run-1",
    )

    summary = coordinator.run_once()

    assert summary.complete is True
    assert summary.source_checkpointed is True
    assert source.marked == ["b" * 40]
    heartbeat = json.loads(store.heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["status"] == "idle"
    persisted = json.loads(store.run_summary_path.read_text(encoding="utf-8"))
    assert persisted["duration_seconds"] == 1.0
    assert persisted["state_seen_ids"] == 1


def test_shadow_run_never_advances_source_checkpoint(tmp_path: Path) -> None:
    source = FakeSource(_download())
    store = StateStore(tmp_path / "state")
    coordinator = RunCoordinator(
        source=source,
        pipeline=FakePipeline(PipelineStatus.SHADOW_READY, store),
        state_store=store,
        clock=_clock(),  # type: ignore[arg-type]
        run_id_factory=lambda: "run-shadow",
    )

    summary = coordinator.run_once()

    assert summary.complete is False
    assert summary.source_checkpointed is False
    assert source.marked == []


def test_unchanged_source_is_a_complete_noop(tmp_path: Path) -> None:
    source = FakeSource(None)
    store = StateStore(tmp_path / "state")
    summary = RunCoordinator(
        source=source,
        pipeline=FakePipeline(PipelineStatus.RESUME_GENERATED, store),
        state_store=store,
        clock=_clock(),  # type: ignore[arg-type]
        run_id_factory=lambda: "run-unchanged",
    ).run_once()

    assert summary.source_changed is False
    assert summary.result is None
    assert source.marked == []


def test_uncommitted_terminal_result_fails_before_source_checkpoint(tmp_path: Path) -> None:
    source = FakeSource(_download())
    store = StateStore(tmp_path / "state")

    class UncommittedPipeline:
        def run(self, listings: object) -> PipelineRunResult:
            del listings
            outcome = PipelineOutcome(
                listing_id="fictional-1",
                status=PipelineStatus.RESUME_GENERATED,
                summary="not actually committed",
                timestamp=START,
            )
            return PipelineRunResult(1, 1, 0, 1, (outcome,))

    coordinator = RunCoordinator(
        source=source,
        pipeline=UncommittedPipeline(),
        state_store=store,
        clock=_clock(),  # type: ignore[arg-type]
        run_id_factory=lambda: "run-uncommitted",
    )

    with pytest.raises(StateCorruptionError, match="missing from the seen-ID"):
        coordinator.run_once()

    assert source.marked == []
    heartbeat = json.loads(store.heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["status"] == "failed"
    assert heartbeat["error_type"] == "StateCorruptionError"


def test_run_id_cannot_inject_controls_into_observability(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    coordinator = RunCoordinator(
        source=FakeSource(None),
        pipeline=FakePipeline(PipelineStatus.RESUME_GENERATED, store),
        state_store=store,
        run_id_factory=lambda: "forged\nstatus",
    )

    with pytest.raises(ValueError, match="no controls"):
        coordinator.run_once()

    assert not store.heartbeat_path.exists()


def test_daemon_waits_after_the_immediate_run() -> None:
    events: list[str] = []
    stopped = threading.Event()

    class Coordinator:
        def run_once(self) -> object:
            events.append("run")
            stopped.set()
            return object()

    run_daemon(Coordinator(), interval_seconds=1, stop_event=stopped)  # type: ignore[arg-type]

    assert events == ["run"]


def test_daemon_serializes_each_interval_after_prior_completion() -> None:
    events: list[str] = []

    class StopAfterTwo:
        def is_set(self) -> bool:
            return False

        def wait(self, timeout: float) -> bool:
            assert timeout == 2
            events.append("wait")
            return events.count("wait") == 2

    class Coordinator:
        def run_once(self) -> object:
            events.append("run")
            return object()

    run_daemon(
        Coordinator(),  # type: ignore[arg-type]
        interval_seconds=2,
        stop_event=StopAfterTwo(),  # type: ignore[arg-type]
    )

    assert events == ["run", "wait", "run", "wait"]


def test_daemon_sigterm_requests_graceful_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    stop_event = threading.Event()
    installed: dict[signal.Signals, object] = {}
    restored: list[tuple[signal.Signals, object]] = []
    previous = object()

    def fake_getsignal(shutdown_signal: signal.Signals) -> object:
        del shutdown_signal
        return previous

    def fake_signal(shutdown_signal: signal.Signals, handler: object) -> object:
        if handler is previous:
            restored.append((shutdown_signal, handler))
        else:
            installed[shutdown_signal] = handler
        return previous

    class Coordinator:
        def run_once(self) -> object:
            handler = installed[signal.SIGTERM]
            assert callable(handler)
            handler(signal.SIGTERM, None)
            return object()

    monkeypatch.setattr("auto_interner.runtime.signal.getsignal", fake_getsignal)
    monkeypatch.setattr("auto_interner.runtime.signal.signal", fake_signal)

    run_daemon(
        Coordinator(),  # type: ignore[arg-type]
        interval_seconds=60,
        stop_event=stop_event,
    )

    assert stop_event.is_set()
    assert {item[0] for item in restored} == {signal.SIGINT, signal.SIGTERM}
