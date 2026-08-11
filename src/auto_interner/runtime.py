"""Non-overlapping runtime coordination, summaries, and daemon scheduling."""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from auto_interner.models import Listing, PipelineRunResult
from auto_interner.run_lock import RunLock
from auto_interner.sources import GitSnapshotLoader, RemoteSnapshotLoader, SnapshotDownload
from auto_interner.state_store import StateCorruptionError, StateReconciliation, StateStore

LOGGER = logging.getLogger(__name__)


class RuntimeSource(Protocol):
    """One swappable snapshot acquisition and checkpoint boundary."""

    def acquire(self) -> SnapshotDownload | None:
        """Return changed source data, or None when the source version was processed."""

    def mark_processed(self, source_version: str) -> None:
        """Checkpoint a source version only after its full scan completes terminally."""


class PipelineRunner(Protocol):
    """Complete application-pipeline surface consumed by the coordinator."""

    def run(self, listings: Iterable[Listing]) -> PipelineRunResult:
        """Process one validated snapshot."""


class GitRuntimeSource:
    """Runtime adapter for the version-aware Git snapshot loader."""

    def __init__(self, loader: GitSnapshotLoader) -> None:
        self._loader = loader

    def acquire(self) -> SnapshotDownload | None:
        return self._loader.download_if_changed()

    def mark_processed(self, source_version: str) -> None:
        self._loader.mark_processed(source_version)


class HttpRuntimeSource:
    """Runtime adapter for an HTTP snapshot without a remote version marker."""

    def __init__(self, loader: RemoteSnapshotLoader, url: str) -> None:
        self._loader = loader
        self._url = url

    def acquire(self) -> SnapshotDownload:
        return self._loader.download(self._url)

    def mark_processed(self, source_version: str) -> None:
        del source_version


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _run_id() -> str:
    return uuid4().hex


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("runtime clock must return timezone-aware timestamps")


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Sanitized, JSON-safe record of one worker run."""

    run_id: str
    started_at: datetime
    finished_at: datetime
    source_changed: bool
    source_version: str | None
    source_anomalies: int
    source_checkpointed: bool
    complete: bool
    result: PipelineRunResult | None
    state: StateReconciliation

    def as_dict(self) -> dict[str, object]:
        """Serialize without listing bodies, model payloads, or résumé content."""
        payload: dict[str, object] = {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "source_changed": self.source_changed,
            "source_anomalies": self.source_anomalies,
            "source_checkpointed": self.source_checkpointed,
            "complete": self.complete,
            "duration_seconds": (self.finished_at - self.started_at).total_seconds(),
        }
        payload.update(self.state.as_dict())
        if self.source_version is not None:
            payload["source_version"] = self.source_version
        if self.result is not None:
            payload.update(self.result.as_dict())
        return payload


class RunCoordinator:
    """Own one complete source-to-state run under a process-wide lock."""

    def __init__(
        self,
        *,
        source: RuntimeSource,
        pipeline: PipelineRunner,
        state_store: StateStore,
        lock_path: Path | None = None,
        clock: Callable[[], datetime] = _utc_now,
        run_id_factory: Callable[[], str] = _run_id,
    ) -> None:
        resolved_lock_path = state_store.state_dir / "run.lock" if lock_path is None else lock_path
        self._source = source
        self._pipeline = pipeline
        self._state_store = state_store
        self._lock_path = resolved_lock_path
        self._clock = clock
        self._run_id_factory = run_id_factory

    @staticmethod
    def _heartbeat(run_id: str, status: str, timestamp: datetime) -> Mapping[str, object]:
        return {"run_id": run_id, "status": status, "timestamp": timestamp.isoformat()}

    def run_once(self) -> RunSummary:
        """Run immediately, checkpointing Git only when every outcome is terminal."""
        with RunLock(self._lock_path):
            run_id = self._run_id_factory()
            if (
                not run_id
                or run_id != run_id.strip()
                or len(run_id) > 200
                or any(ord(character) < 32 or ord(character) == 127 for character in run_id)
            ):
                raise ValueError("run ID must be nonempty, bounded, and contain no controls")
            started_at = self._clock()
            _require_aware(started_at)
            self._state_store.write_heartbeat(self._heartbeat(run_id, "running", started_at))
            try:
                download = self._source.acquire()
                if download is None:
                    state = self._state_store.reconcile()
                    finished_at = self._clock()
                    _require_aware(finished_at)
                    summary = RunSummary(
                        run_id=run_id,
                        started_at=started_at,
                        finished_at=finished_at,
                        source_changed=False,
                        source_version=None,
                        source_anomalies=0,
                        source_checkpointed=False,
                        complete=True,
                        result=None,
                        state=state,
                    )
                else:
                    result = self._pipeline.run(download.snapshot.listings)
                    complete = all(outcome.is_terminal for outcome in result.outcomes)
                    terminal_outcome_ids = {
                        outcome.listing_id for outcome in result.outcomes if outcome.is_terminal
                    }
                    if not terminal_outcome_ids <= self._state_store.load_seen_ids():
                        raise StateCorruptionError(
                            "terminal run outcomes are missing from the seen-ID state"
                        )
                    state = self._state_store.reconcile()
                    checkpointed = False
                    if complete and download.source_version is not None:
                        self._source.mark_processed(download.source_version)
                        checkpointed = True
                    finished_at = self._clock()
                    _require_aware(finished_at)
                    summary = RunSummary(
                        run_id=run_id,
                        started_at=started_at,
                        finished_at=finished_at,
                        source_changed=True,
                        source_version=download.source_version,
                        source_anomalies=len(download.snapshot.anomalies),
                        source_checkpointed=checkpointed,
                        complete=complete,
                        result=result,
                        state=state,
                    )
                self._state_store.record_run_summary(summary.as_dict())
                self._state_store.write_heartbeat(
                    self._heartbeat(run_id, "idle", summary.finished_at)
                )
                return summary
            except Exception as exc:
                failed_at = self._clock()
                _require_aware(failed_at)
                self._state_store.write_heartbeat(
                    {
                        **self._heartbeat(run_id, "failed", failed_at),
                        "error_type": type(exc).__name__,
                    }
                )
                raise


def run_daemon(
    coordinator: RunCoordinator,
    *,
    interval_seconds: float,
    stop_event: threading.Event,
) -> None:
    """Run immediately, then wait only after completion so runs never overlap."""
    if interval_seconds <= 0:
        raise ValueError("daemon interval must be positive")
    previous_handlers: dict[signal.Signals, Any] = {}

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    if threading.current_thread() is threading.main_thread():
        for registered_signal in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[registered_signal] = signal.getsignal(registered_signal)
            signal.signal(registered_signal, request_stop)
    try:
        while not stop_event.is_set():
            try:
                coordinator.run_once()
            except Exception as exc:
                LOGGER.error(
                    "Scheduled run failed",
                    extra={"event": "scheduled_run_failed", "error_type": type(exc).__name__},
                )
            if stop_event.wait(interval_seconds):
                return
    finally:
        for saved_signal, previous_handler in previous_handlers.items():
            signal.signal(saved_signal, previous_handler)
