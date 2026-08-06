"""Complete single-writer listing-to-resume orchestration for Phase 6."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from auto_interner.dedupe import RoleDeduplicator
from auto_interner.documents.assembler import DocumentAssemblyError, assemble_resume
from auto_interner.documents.template_reader import ResumeStructureError, read_resume
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
from auto_interner.paths import (
    OutputCollisionError,
    OutputPathError,
    OutputPathPlanner,
)
from auto_interner.pipeline import PipelineRunResult
from auto_interner.rewriting.service import (
    RewriteResponseError,
    UnsupportedRewriteError,
    request_validated_rewrite,
)
from auto_interner.scanner import iter_unseen_windows
from auto_interner.screening.keywords import screen_posting_text
from auto_interner.screening.location import LocationScreenStatus, screen_locations
from auto_interner.screening.semantic import SemanticResponseError, screen_posting_semantically
from auto_interner.state_store import StateStore


class PostingFetcher(Protocol):
    """Replaceable posting-text acquisition boundary."""

    def fetch(self, listing: Listing, *, attempt_number: int) -> FetchResult:
        """Return one classified fetch result without writing state."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ApplicationPipeline:
    """Sequence every established stage under one injected state owner."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        fetcher: PostingFetcher,
        model_client: StructuredModelClient,
        output_planner: OutputPathPlanner,
        deduplicator: RoleDeduplicator,
        base_resume_path: Path,
        shadow_mode: bool,
        window_size: int = 100,
        max_attempts: int = 3,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if window_size <= 0 or max_attempts <= 0:
            raise ValueError("pipeline window and attempt limits must be positive")
        self._state_store = state_store
        self._fetcher = fetcher
        self._model_client = model_client
        self._output_planner = output_planner
        self._deduplicator = deduplicator
        self._base_resume_path = base_resume_path
        self._shadow_mode = shadow_mode
        self._window_size = window_size
        self._max_attempts = max_attempts
        self._clock = clock

    def _manual(
        self,
        listing: Listing,
        *,
        stage: str,
        attempt_number: int,
        timestamp: datetime,
    ) -> PipelineOutcome:
        return self._state_store.send_to_manual_review(
            listing,
            reason=f"{stage} failed permanently",
            attempt_number=attempt_number,
            timestamp=timestamp,
        )

    def _retry(
        self,
        listing: Listing,
        *,
        stage: str,
        timestamp: datetime,
    ) -> PipelineOutcome:
        return self._state_store.record_retry(
            listing,
            reason=f"{stage} failed temporarily",
            max_attempts=self._max_attempts,
            timestamp=timestamp,
        )

    def _commit_disqualification(
        self,
        listing: Listing,
        decision: ScreeningDecision,
        *,
        summary: str,
        timestamp: datetime,
        attempt_number: int | None = None,
    ) -> PipelineOutcome:
        outcome = PipelineOutcome(
            listing_id=listing.id,
            status=PipelineStatus.DISQUALIFIED,
            summary=summary,
            timestamp=timestamp,
            decision=decision,
            attempt_number=attempt_number,
        )
        self._state_store.commit_terminal(outcome)
        return outcome

    def _location_decision(self, listing: Listing, timestamp: datetime) -> ScreeningDecision:
        return ScreeningDecision(
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

    def process_listing(self, listing: Listing) -> PipelineOutcome:
        """Run one listing to a terminal artifact/decision or explicit retry/shadow state."""
        timestamp = self._clock()
        if screen_locations(listing.locations).status is LocationScreenStatus.DISQUALIFY:
            return self._commit_disqualification(
                listing,
                self._location_decision(listing, timestamp),
                summary="structured locations are outside the United States",
                timestamp=timestamp,
            )

        attempt_number = self._state_store.load_retry_counts().get(listing.id, 0) + 1
        try:
            fetch_result = self._fetcher.fetch(listing, attempt_number=attempt_number)
        except Exception:
            return self._retry(listing, stage="posting fetch", timestamp=timestamp)
        if fetch_result.listing_id != listing.id or fetch_result.attempt_number != attempt_number:
            return self._manual(
                listing,
                stage="posting fetch identity",
                attempt_number=attempt_number,
                timestamp=timestamp,
            )
        if fetch_result.status is FetchStatus.RETRYABLE_FAILURE:
            return self._retry(listing, stage="posting fetch", timestamp=timestamp)
        if fetch_result.status is FetchStatus.PERMANENT_FAILURE:
            return self._manual(
                listing,
                stage="posting fetch",
                attempt_number=attempt_number,
                timestamp=timestamp,
            )
        if fetch_result.method is None or not fetch_result.text.strip():
            return self._retry(listing, stage="posting fetch", timestamp=timestamp)

        decision = screen_posting_text(listing.id, fetch_result.text, decided_at=timestamp)
        if decision is not None:
            return self._commit_disqualification(
                listing,
                decision,
                summary="posting text contains a configured hard disqualifier",
                timestamp=timestamp,
                attempt_number=attempt_number,
            )

        try:
            decision = screen_posting_semantically(
                self._model_client,
                listing.id,
                fetch_result.text,
                decided_at=timestamp,
            )
        except (ModelBoundaryError, SemanticResponseError) as exc:
            if getattr(exc, "retryable", True):
                return self._retry(listing, stage="semantic screening", timestamp=timestamp)
            return self._manual(
                listing,
                stage="semantic screening",
                attempt_number=attempt_number,
                timestamp=timestamp,
            )
        except Exception:
            return self._retry(listing, stage="semantic screening", timestamp=timestamp)
        if decision is not None:
            return self._commit_disqualification(
                listing,
                decision,
                summary="semantic screening found a hard disqualifier",
                timestamp=timestamp,
                attempt_number=attempt_number,
            )

        try:
            dedupe = self._deduplicator.check(listing, as_of=timestamp)
        except OSError:
            return self._retry(listing, stage="role deduplication", timestamp=timestamp)
        if dedupe.is_duplicate:
            outcome = PipelineOutcome(
                listing_id=listing.id,
                status=PipelineStatus.DEDUPE_SKIPPED,
                summary="a recent generated resume already covers this company and role",
                timestamp=timestamp,
                output_path=dedupe.matched_path,
                attempt_number=attempt_number,
            )
            self._state_store.commit_terminal(outcome)
            return outcome

        try:
            resume = read_resume(self._base_resume_path)
            rewrite = request_validated_rewrite(
                self._model_client,
                resume,
                fetch_result.text,
            )
            output_plan = self._output_planner.plan(listing, generated_at=timestamp)
        except (ResumeStructureError, UnsupportedRewriteError, OutputPathError, TypeError):
            return self._manual(
                listing,
                stage="resume planning",
                attempt_number=attempt_number,
                timestamp=timestamp,
            )
        except (ModelBoundaryError, RewriteResponseError) as exc:
            if getattr(exc, "retryable", True):
                return self._retry(listing, stage="resume rewrite", timestamp=timestamp)
            return self._manual(
                listing,
                stage="resume rewrite",
                attempt_number=attempt_number,
                timestamp=timestamp,
            )
        except (OSError, ValueError):
            return self._retry(listing, stage="resume planning", timestamp=timestamp)

        if self._shadow_mode:
            outcome = PipelineOutcome(
                listing_id=listing.id,
                status=PipelineStatus.SHADOW_READY,
                summary="shadow mode validated the intended resume without writing it",
                timestamp=timestamp,
                output_path=output_plan.output_path,
                attempt_number=attempt_number,
            )
            self._state_store.record_outcome(outcome)
            self._state_store.clear_retry_count(listing.id)
            return outcome

        try:
            destination = self._output_planner.prepare(output_plan)
            assembly = assemble_resume(resume, rewrite, destination)
        except (OutputCollisionError, OutputPathError, ResumeStructureError):
            return self._manual(
                listing,
                stage="document publication",
                attempt_number=attempt_number,
                timestamp=timestamp,
            )
        except (DocumentAssemblyError, OSError):
            return self._retry(listing, stage="document assembly", timestamp=timestamp)
        outcome = PipelineOutcome(
            listing_id=listing.id,
            status=PipelineStatus.RESUME_GENERATED,
            summary="validated tailored resume generated for human review",
            timestamp=timestamp,
            output_path=assembly.output_path,
            attempt_number=attempt_number,
        )
        self._state_store.commit_terminal(outcome)
        return outcome

    def run(self, listings: Iterable[Listing]) -> PipelineRunResult:
        """Process active unseen listings in bounded deterministic windows."""
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
