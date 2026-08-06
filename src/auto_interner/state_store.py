"""Single-writer, crash-aware local state persistence."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from auto_interner.models import Listing, PipelineOutcome, PipelineStatus, ScreeningDecision


class StateCorruptionError(ValueError):
    """Raised when persisted state cannot be trusted or recovered silently."""


class CommitPoint(StrEnum):
    """Fault-injection boundaries around a terminal state commit."""

    BEFORE_DECISION = "before_decision"
    AFTER_DECISION = "after_decision"
    AFTER_SEEN = "after_seen"


class FaultInjector(Protocol):
    """Test seam for crash-boundary verification."""

    def trigger(self, point: CommitPoint) -> None:
        """Raise or return at a named commit boundary."""


class _NoFaults:
    def trigger(self, point: CommitPoint) -> None:
        del point


@dataclass(frozen=True, slots=True)
class StateReconciliation:
    """Counts proving seen, terminal, and manual-review state can be reconciled."""

    seen_ids: int
    terminal_decisions: int
    manual_review_ids: int
    terminal_awaiting_seen: int
    manual_awaiting_terminal: int

    def as_dict(self) -> dict[str, object]:
        return {
            "state_seen_ids": self.seen_ids,
            "state_terminal_decisions": self.terminal_decisions,
            "state_manual_review_ids": self.manual_review_ids,
            "state_terminal_awaiting_seen": self.terminal_awaiting_seen,
            "state_manual_awaiting_terminal": self.manual_awaiting_terminal,
        }


def _sanitize_reason(reason: str) -> str:
    normalized = " ".join(reason.split())
    return (normalized or "unspecified failure")[:500]


def _validate_listing_id(listing_id: str) -> None:
    if (
        not listing_id
        or listing_id != listing_id.strip()
        or len(listing_id) > 500
        or any(ord(character) < 32 or ord(character) == 127 for character in listing_id)
    ):
        raise ValueError("listing ID must be nonempty and contain no control characters")


def _decision_record(decision: ScreeningDecision) -> dict[str, object]:
    return {
        "listing_id": decision.listing_id,
        "outcome": decision.outcome,
        "decided_at": decision.decided_at.isoformat(),
        "evidence": [
            {
                "category": item.category,
                "decision": item.decision,
                "confidence": item.confidence,
                "tier": item.tier,
                "evidence": item.evidence,
            }
            for item in decision.evidence
        ],
    }


def _outcome_record(outcome: PipelineOutcome) -> dict[str, object]:
    record: dict[str, object] = {
        "listing_id": outcome.listing_id,
        "status": outcome.status,
        "summary": outcome.summary,
        "timestamp": outcome.timestamp.isoformat(),
        "terminal": outcome.is_terminal,
    }
    if outcome.attempt_number is not None:
        record["attempt_number"] = outcome.attempt_number
    if outcome.output_path is not None:
        record["output_path"] = str(outcome.output_path)
    if outcome.decision is not None:
        record["screening"] = _decision_record(outcome.decision)
    return record


class StateStore:
    """Own all Phase 1 state writes under one configured directory."""

    def __init__(self, state_dir: Path, *, fault_injector: FaultInjector | None = None) -> None:
        self.state_dir = state_dir
        self.seen_path = state_dir / "seen_listing_ids.txt"
        self.retry_path = state_dir / "retry_counts.json"
        self.decisions_path = state_dir / "decisions.jsonl"
        self.manual_review_path = state_dir / "manual_review_queue.jsonl"
        self.run_summary_path = state_dir / "run_summaries.jsonl"
        self.heartbeat_path = state_dir / "heartbeat.json"
        self.tmp_dir = state_dir / "tmp"
        self._fault_injector = fault_injector or _NoFaults()

    def load_seen_ids(self) -> set[str]:
        """Load every nonempty seen ID once and discard duplicate lines."""
        if not self.seen_path.exists():
            return set()
        seen_ids: set[str] = set()
        for line in self.seen_path.read_text(encoding="utf-8").splitlines():
            listing_id = line.strip()
            if not listing_id:
                continue
            try:
                _validate_listing_id(listing_id)
            except ValueError as exc:
                raise StateCorruptionError("seen-ID state contains an invalid ID") from exc
            seen_ids.add(listing_id)
        return seen_ids

    def load_retry_counts(self) -> dict[str, int]:
        """Load validated retry counts or report corruption explicitly."""
        if not self.retry_path.exists():
            return {}
        try:
            payload = cast(object, json.loads(self.retry_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateCorruptionError(f"retry state is unreadable: {self.retry_path}") from exc
        if not isinstance(payload, dict):
            raise StateCorruptionError("retry state must be a JSON object")
        raw_counts = cast(dict[object, object], payload)
        counts: dict[str, int] = {}
        for listing_id, count in raw_counts.items():
            if (
                not isinstance(listing_id, str)
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count < 0
            ):
                raise StateCorruptionError("retry state contains an invalid ID or count")
            try:
                _validate_listing_id(listing_id)
            except ValueError as exc:
                raise StateCorruptionError("retry state contains an invalid ID or count") from exc
            counts[listing_id] = count
        return counts

    def _ensure_write_layout(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def _atomic_write_json(self, path: Path, payload: Mapping[str, object]) -> None:
        self._ensure_write_layout()
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.tmp_dir, prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(dict(sorted(payload.items())), handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    def _append_jsonl(self, path: Path, record: Mapping[str, object]) -> None:
        self._ensure_write_layout()
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _append_seen_id(self, listing_id: str) -> None:
        self._ensure_write_layout()
        with self.seen_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{listing_id}\n")
            handle.flush()
            os.fsync(handle.fileno())

    def record_outcome(self, outcome: PipelineOutcome) -> None:
        """Append a nonterminal outcome without changing the seen set."""
        _validate_listing_id(outcome.listing_id)
        if outcome.is_terminal:
            raise ValueError("terminal outcomes must use commit_terminal")
        self._append_jsonl(self.decisions_path, _outcome_record(outcome))

    def clear_retry_count(self, listing_id: str) -> None:
        """Forget prior transient failures after a usable fetch succeeds."""
        _validate_listing_id(listing_id)
        counts = self.load_retry_counts()
        if listing_id not in counts:
            return
        del counts[listing_id]
        self._atomic_write_json(self.retry_path, counts)

    def _jsonl_has_listing_id(
        self,
        path: Path,
        listing_id: str,
        *,
        require_terminal: bool = False,
    ) -> bool:
        if not path.exists():
            return False
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise StateCorruptionError(f"state log is unreadable: {path}") from exc
        for line in lines:
            try:
                record = cast(object, json.loads(line))
            except json.JSONDecodeError as exc:
                raise StateCorruptionError(f"state log contains invalid JSON: {path}") from exc
            if (
                isinstance(record, dict)
                and record.get("listing_id") == listing_id
                and (not require_terminal or record.get("terminal") is True)
            ):
                return True
        return False

    def _jsonl_listing_ids(
        self,
        path: Path,
        *,
        require_terminal: bool = False,
    ) -> set[str]:
        if not path.exists():
            return set()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise StateCorruptionError(f"state log is unreadable: {path}") from exc
        listing_ids: set[str] = set()
        for line in lines:
            try:
                record = cast(object, json.loads(line))
            except json.JSONDecodeError as exc:
                raise StateCorruptionError(f"state log contains invalid JSON: {path}") from exc
            if not isinstance(record, dict) or not isinstance(record.get("listing_id"), str):
                raise StateCorruptionError(f"state log contains an invalid record: {path}")
            listing_id = record["listing_id"]
            try:
                _validate_listing_id(listing_id)
            except ValueError as exc:
                raise StateCorruptionError(f"state log contains an invalid ID: {path}") from exc
            if not require_terminal or record.get("terminal") is True:
                listing_ids.add(listing_id)
        return listing_ids

    def commit_terminal(self, outcome: PipelineOutcome) -> bool:
        """Write decision then seen ID; return False for an existing terminal ID."""
        _validate_listing_id(outcome.listing_id)
        if not outcome.is_terminal:
            raise ValueError("only terminal outcomes can join the seen set")
        if outcome.listing_id in self.load_seen_ids():
            return False

        decision_exists = self._jsonl_has_listing_id(
            self.decisions_path,
            outcome.listing_id,
            require_terminal=True,
        )
        self._fault_injector.trigger(CommitPoint.BEFORE_DECISION)
        if not decision_exists:
            self._append_jsonl(self.decisions_path, _outcome_record(outcome))
        self._fault_injector.trigger(CommitPoint.AFTER_DECISION)
        self._append_seen_id(outcome.listing_id)
        self._fault_injector.trigger(CommitPoint.AFTER_SEEN)

        counts = self.load_retry_counts()
        if outcome.listing_id in counts:
            del counts[outcome.listing_id]
            self._atomic_write_json(self.retry_path, counts)
        return True

    def send_to_manual_review(
        self,
        listing: Listing,
        *,
        reason: str,
        attempt_number: int,
        timestamp: datetime,
    ) -> PipelineOutcome:
        """Write a bounded manual-review record, then commit a terminal outcome."""
        _validate_listing_id(listing.id)
        sanitized_reason = _sanitize_reason(reason)
        if not self._jsonl_has_listing_id(self.manual_review_path, listing.id):
            self._append_jsonl(
                self.manual_review_path,
                {
                    "listing_id": listing.id,
                    "company_name": listing.company_name,
                    "title": listing.title,
                    "url": listing.url,
                    "attempt_number": attempt_number,
                    "failure_reason": sanitized_reason,
                    "timestamp": timestamp.isoformat(),
                },
            )
        outcome = PipelineOutcome(
            listing_id=listing.id,
            status=PipelineStatus.MANUAL_REVIEW,
            summary="listing requires manual review after automated processing failed",
            timestamp=timestamp,
            attempt_number=attempt_number,
        )
        self.commit_terminal(outcome)
        return outcome

    def record_retry(
        self,
        listing: Listing,
        *,
        reason: str,
        max_attempts: int,
        timestamp: datetime,
    ) -> PipelineOutcome:
        """Increment a cross-run retry or terminally enqueue exhausted work."""
        _validate_listing_id(listing.id)
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        counts = self.load_retry_counts()
        attempt_number = counts.get(listing.id, 0) + 1
        counts[listing.id] = attempt_number
        self._atomic_write_json(self.retry_path, counts)

        if attempt_number >= max_attempts:
            return self.send_to_manual_review(
                listing,
                reason=reason,
                attempt_number=attempt_number,
                timestamp=timestamp,
            )

        outcome = PipelineOutcome(
            listing_id=listing.id,
            status=PipelineStatus.RETRYABLE_FAILURE,
            summary=_sanitize_reason(reason),
            timestamp=timestamp,
            attempt_number=attempt_number,
        )
        self.record_outcome(outcome)
        return outcome

    def record_run_summary(self, summary: Mapping[str, object]) -> None:
        """Append one sanitized run summary without posting or resume content."""
        self._append_jsonl(self.run_summary_path, summary)

    def write_heartbeat(self, heartbeat: Mapping[str, object]) -> None:
        """Atomically publish the latest worker lifecycle heartbeat."""
        self._atomic_write_json(self.heartbeat_path, heartbeat)

    def manual_review_count(self) -> int:
        """Count unique listing IDs currently recorded for manual review."""
        return len(self._jsonl_listing_ids(self.manual_review_path))

    def reconcile(self) -> StateReconciliation:
        """Validate cross-file state and report recoverable commit-boundary gaps."""
        seen_ids = self.load_seen_ids()
        terminal_ids = self._jsonl_listing_ids(
            self.decisions_path,
            require_terminal=True,
        )
        manual_ids = self._jsonl_listing_ids(self.manual_review_path)
        missing_terminal = seen_ids - terminal_ids
        if missing_terminal:
            raise StateCorruptionError("seen-ID state contains IDs without terminal decisions")
        return StateReconciliation(
            seen_ids=len(seen_ids),
            terminal_decisions=len(terminal_ids),
            manual_review_ids=len(manual_ids),
            terminal_awaiting_seen=len(terminal_ids - seen_ids),
            manual_awaiting_terminal=len(manual_ids - terminal_ids),
        )
