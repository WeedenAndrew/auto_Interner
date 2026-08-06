"""Offline orchestration for source, screening, and state components."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from auto_interner.model_client import ModelBoundaryError, StructuredModelClient
from auto_interner.models import (
    Confidence,
    EvidenceDecision,
    FetchResult,
    FetchStatus,
    Listing,
    PipelineOutcome,
    PipelineStatus,
    ScreeningCategory,
    ScreeningDecision,
    ScreeningEvidence,
    ScreeningOutcome,
    ScreeningTier,
)
from auto_interner.scanner import iter_unseen_windows
from auto_interner.screening.keywords import screen_posting_text
from auto_interner.screening.location import LocationScreenStatus, screen_locations
from auto_interner.screening.semantic import SemanticResponseError, screen_posting_semantically
from auto_interner.state_store import StateStore


class PostingFetcher(Protocol):
    """Replaceable boundary for acquiring posting text."""

    def fetch(self, listing: Listing, *, attempt_number: int) -> FetchResult:
        """Return posting text or a classified failure without writing state."""


@dataclass(frozen=True, slots=True)
class PipelineRunResult:
    """Deterministic summary of one offline pipeline run."""

    source_records: int
    active_records: int
    skipped_seen: int
    windows_processed: int
    outcomes: tuple[PipelineOutcome, ...]

    @property
    def status_counts(self) -> dict[str, int]:
        """Count outcomes by their stable serialized status."""
        return dict(Counter(outcome.status.value for outcome in self.outcomes))

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe public summary with no posting bodies."""
        return {
            "source_records": self.source_records,
            "active_records": self.active_records,
            "skipped_seen": self.skipped_seen,
            "windows_processed": self.windows_processed,
            "processed": len(self.outcomes),
            "terminal": sum(outcome.is_terminal for outcome in self.outcomes),
            "status_counts": self.status_counts,
        }


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OfflinePipeline:
    """Run deterministic Phase 1 behavior with injected external boundaries."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        fetcher: PostingFetcher,
        window_size: int = 100,
        max_fetch_attempts: int = 3,
        semantic_client: StructuredModelClient | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        if max_fetch_attempts <= 0:
            raise ValueError("max_fetch_attempts must be positive")
        self._state_store = state_store
        self._fetcher = fetcher
        self._window_size = window_size
        self._max_fetch_attempts = max_fetch_attempts
        self._semantic_client = semantic_client
        self._clock = clock

    def _location_outcome(self, listing: Listing, timestamp: datetime) -> PipelineOutcome:
        decision = ScreeningDecision(
            listing_id=listing.id,
            outcome=ScreeningOutcome.DISQUALIFY,
            evidence=(
                ScreeningEvidence(
                    category=ScreeningCategory.LOCATION,
                    decision=EvidenceDecision.DISQUALIFY,
                    confidence=Confidence.HIGH,
                    tier=ScreeningTier.STRUCTURED_LOCATION,
                    evidence="all structured locations are recognized as outside the United States",
                ),
            ),
            decided_at=timestamp,
        )
        return PipelineOutcome(
            listing_id=listing.id,
            status=PipelineStatus.DISQUALIFIED,
            summary="structured locations are outside the United States",
            timestamp=timestamp,
            decision=decision,
        )

    def _retry(self, listing: Listing, reason: str, timestamp: datetime) -> PipelineOutcome:
        return self._state_store.record_retry(
            listing,
            reason=reason,
            max_attempts=self._max_fetch_attempts,
            timestamp=timestamp,
        )

    def process_listing(self, listing: Listing) -> PipelineOutcome:
        """Process one listing and persist its outcome through the state owner."""
        timestamp = self._clock()
        location_result = screen_locations(listing.locations)
        if location_result.status is LocationScreenStatus.DISQUALIFY:
            outcome = self._location_outcome(listing, timestamp)
            self._state_store.commit_terminal(outcome)
            return outcome

        attempt_number = self._state_store.load_retry_counts().get(listing.id, 0) + 1
        try:
            fetch_result = self._fetcher.fetch(listing, attempt_number=attempt_number)
        except Exception as exc:
            reason = f"posting fetch raised {type(exc).__name__}"
            return self._retry(listing, reason, timestamp)

        if fetch_result.listing_id != listing.id or fetch_result.attempt_number != attempt_number:
            return self._state_store.send_to_manual_review(
                listing,
                reason="posting fetcher returned an invalid result identity",
                attempt_number=attempt_number,
                timestamp=timestamp,
            )
        if fetch_result.status is FetchStatus.RETRYABLE_FAILURE:
            return self._retry(
                listing,
                fetch_result.failure_reason or "posting fetch failed temporarily",
                timestamp,
            )
        if fetch_result.status is FetchStatus.PERMANENT_FAILURE:
            return self._state_store.send_to_manual_review(
                listing,
                reason=fetch_result.failure_reason or "posting fetch failed permanently",
                attempt_number=attempt_number,
                timestamp=timestamp,
            )
        if fetch_result.method is None or not fetch_result.text.strip():
            return self._retry(
                listing,
                "posting fetch returned no usable text",
                timestamp,
            )

        decision = screen_posting_text(
            listing.id,
            fetch_result.text,
            decided_at=timestamp,
        )
        if decision is not None:
            outcome = PipelineOutcome(
                listing_id=listing.id,
                status=PipelineStatus.DISQUALIFIED,
                summary="posting text contains a configured hard disqualifier",
                timestamp=timestamp,
                decision=decision,
                attempt_number=attempt_number,
            )
            self._state_store.commit_terminal(outcome)
            return outcome

        if self._semantic_client is not None:
            try:
                decision = screen_posting_semantically(
                    self._semantic_client,
                    listing.id,
                    fetch_result.text,
                    decided_at=timestamp,
                )
            except (ModelBoundaryError, SemanticResponseError) as exc:
                reason = f"semantic screening failed: {type(exc).__name__}"
                if getattr(exc, "retryable", True):
                    return self._retry(listing, reason, timestamp)
                return self._state_store.send_to_manual_review(
                    listing,
                    reason=reason,
                    attempt_number=attempt_number,
                    timestamp=timestamp,
                )
            except Exception as exc:
                return self._retry(
                    listing,
                    f"semantic screening raised {type(exc).__name__}",
                    timestamp,
                )
            if decision is not None:
                outcome = PipelineOutcome(
                    listing_id=listing.id,
                    status=PipelineStatus.DISQUALIFIED,
                    summary="semantic screening found a hard disqualifier",
                    timestamp=timestamp,
                    decision=decision,
                    attempt_number=attempt_number,
                )
                self._state_store.commit_terminal(outcome)
                return outcome

        outcome = PipelineOutcome(
            listing_id=listing.id,
            status=PipelineStatus.SCREENING_PASSED,
            summary=(
                "semantic screening passed; later stages remain pending"
                if self._semantic_client is not None
                else "deterministic screening passed; later stages remain pending"
            ),
            timestamp=timestamp,
            attempt_number=attempt_number,
        )
        self._state_store.record_outcome(outcome)
        self._state_store.clear_retry_count(listing.id)
        return outcome

    def run(self, listings: Iterable[Listing]) -> PipelineRunResult:
        """Scan a complete snapshot and process each active unseen ID once."""
        snapshot = tuple(listings)
        seen_ids = self._state_store.load_seen_ids()
        active_ids = {listing.id for listing in snapshot if listing.active}
        skipped_seen = len(active_ids & seen_ids)
        outcomes: list[PipelineOutcome] = []
        windows_processed = 0

        for window in iter_unseen_windows(snapshot, seen_ids, self._window_size):
            windows_processed += 1
            for listing in window:
                outcome = self.process_listing(listing)
                outcomes.append(outcome)
                if outcome.is_terminal:
                    seen_ids.add(listing.id)

        return PipelineRunResult(
            source_records=len(snapshot),
            active_records=sum(listing.active for listing in snapshot),
            skipped_seen=skipped_seen,
            windows_processed=windows_processed,
            outcomes=tuple(outcomes),
        )
