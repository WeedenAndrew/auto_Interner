"""Complete single-writer listing-to-resume orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

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
    PipelineRunResult,
    PipelineStatus,
    PostingFetcher,
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
from auto_interner.rewriting.grading import GradeResponseError
from auto_interner.rewriting.loop import MAX_ATTEMPTS, request_graded_rewrite
from auto_interner.rewriting.service import (
    RewriteResponseError,
    UnsupportedRewriteError,
)
from auto_interner.scanner import iter_unseen_windows
from auto_interner.screening.eligibility import screen_listing_eligibility
from auto_interner.screening.keywords import screen_posting_text
from auto_interner.screening.location import LocationScreenStatus, screen_locations
from auto_interner.screening.semantic import SemanticResponseError, screen_posting_semantically
from auto_interner.screening.semantic_cache import (
    CachedVerdict,
    plan_lookup,
    resolve_disagreement,
)
from auto_interner.state_store import StateStore


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _reason(stage: str, disposition: str, detail: str | None) -> str:
    """Name the failing stage, adding an adapter's sanitized detail when it has one."""
    if detail is None or not detail.strip():
        return f"{stage} {disposition}"
    return f"{stage} {disposition}: {detail.strip()}"


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
        recruiting_year: int,
        window_size: int = 100,
        max_attempts: int = 3,
        max_rewrite_attempts: int = MAX_ATTEMPTS,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        if max_attempts <= 0:
            raise ValueError("max_fetch_attempts must be positive")
        if max_rewrite_attempts <= 0:
            raise ValueError("max_rewrite_attempts must be positive")
        self._max_rewrite_attempts = max_rewrite_attempts
        self._recruiting_year = recruiting_year
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
        detail: str | None = None,
    ) -> PipelineOutcome:
        return self._state_store.send_to_manual_review(
            listing,
            reason=_reason(stage, "failed permanently", detail),
            attempt_number=attempt_number,
            timestamp=timestamp,
        )

    def _retry(
        self,
        listing: Listing,
        *,
        stage: str,
        timestamp: datetime,
        detail: str | None = None,
    ) -> PipelineOutcome:
        return self._state_store.record_retry(
            listing,
            reason=_reason(stage, "failed temporarily", detail),
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

    def _semantic_decision(
        self,
        listing: Listing,
        fetch_result: FetchResult,
        *,
        timestamp: datetime,
    ) -> ScreeningDecision | None:
        """Return the Tier 2 verdict, reusing an unexpired cached one when present.

        Raises whatever the model boundary raises, so the caller keeps its single
        retry and manual-review policy for this stage.
        """
        content_key = fetch_result.content_hash
        cache = self._state_store.load_semantic_cache()
        cached = cache.get(content_key) if content_key is not None else None
        lookup = plan_lookup(cached, now=timestamp)

        if not lookup.screen_again and lookup.reuse is not None:
            if not lookup.reuse.disqualified:
                return None
            return ScreeningDecision(
                listing_id=listing.id,
                outcome=ScreeningOutcome.DISQUALIFY,
                evidence=(
                    ScreeningEvidence(
                        category=ScreeningCategory(lookup.reuse.category),
                        decision=EvidenceDecision.DISQUALIFY,
                        confidence=Confidence.HIGH,
                        tier=ScreeningTier.SEMANTIC,
                        evidence=lookup.reuse.summary,
                    ),
                ),
                decided_at=timestamp,
            )

        fresh = screen_posting_semantically(
            self._model_client,
            listing.id,
            fetch_result.text,
            decided_at=timestamp,
        )
        acted, drift = resolve_disagreement(
            lookup.reuse if lookup.screen_again else None,
            fresh_disqualified=fresh is not None,
        )
        if content_key is not None:
            self._state_store.record_semantic_verdict(
                content_key,
                CachedVerdict(
                    disqualified=fresh is not None,
                    screened_at=timestamp,
                    summary=(
                        fresh.evidence[0].evidence if fresh is not None and fresh.evidence else ""
                    ),
                    category=(
                        fresh.evidence[0].category.value
                        if fresh is not None and fresh.evidence
                        else ""
                    ),
                ),
            )
        if drift is not None:
            self._state_store.record_semantic_drift(listing.id, drift)
        return fresh if acted else None

    def process_listing(self, listing: Listing) -> PipelineOutcome:
        """Run one listing to a terminal artifact/decision or explicit retry/shadow state."""
        timestamp = self._clock()

        # Cheapest gate first. This reads fields the snapshot already carries, so
        # an off-season, graduate-only or off-discipline listing is decided
        # before it costs a fetch, let alone a model call.
        eligibility = screen_listing_eligibility(
            listing,
            recruiting_year=self._recruiting_year,
            decided_at=timestamp,
        )
        if eligibility is not None:
            return self._commit_disqualification(
                listing,
                eligibility,
                summary="structured listing fields fall outside the configured search",
                timestamp=timestamp,
            )

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
        except Exception as exc:
            return self._retry(
                listing,
                stage="posting fetch",
                timestamp=timestamp,
                detail=f"adapter raised {type(exc).__name__}",
            )
        if fetch_result.listing_id != listing.id or fetch_result.attempt_number != attempt_number:
            return self._manual(
                listing,
                stage="posting fetch identity",
                attempt_number=attempt_number,
                timestamp=timestamp,
            )
        if fetch_result.status is FetchStatus.RETRYABLE_FAILURE:
            return self._retry(
                listing,
                stage="posting fetch",
                timestamp=timestamp,
                detail=fetch_result.failure_reason,
            )
        if fetch_result.status is FetchStatus.PERMANENT_FAILURE:
            return self._manual(
                listing,
                stage="posting fetch",
                attempt_number=attempt_number,
                timestamp=timestamp,
                detail=fetch_result.failure_reason,
            )
        if fetch_result.method is None or not fetch_result.text.strip():
            return self._retry(
                listing,
                stage="posting fetch",
                timestamp=timestamp,
                detail="adapter returned no usable text",
            )

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
            decision = self._semantic_decision(listing, fetch_result, timestamp=timestamp)
        except (ModelBoundaryError, SemanticResponseError) as exc:
            detail = f"boundary raised {type(exc).__name__}"
            if getattr(exc, "retryable", True):
                return self._retry(
                    listing,
                    stage="semantic screening",
                    timestamp=timestamp,
                    detail=detail,
                )
            return self._manual(
                listing,
                stage="semantic screening",
                attempt_number=attempt_number,
                timestamp=timestamp,
                detail=detail,
            )
        except Exception as exc:
            return self._retry(
                listing,
                stage="semantic screening",
                timestamp=timestamp,
                detail=f"boundary raised {type(exc).__name__}",
            )
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
            graded = request_graded_rewrite(
                self._model_client,
                resume,
                fetch_result.text,
                max_attempts=self._max_rewrite_attempts,
            )
            rewrite = graded.plan
            output_plan = self._output_planner.plan(listing, generated_at=timestamp)
        except (ResumeStructureError, UnsupportedRewriteError, OutputPathError, TypeError) as exc:
            return self._manual(
                listing,
                stage="resume planning",
                attempt_number=attempt_number,
                timestamp=timestamp,
                detail=f"rejected by {type(exc).__name__}",
            )
        except (ModelBoundaryError, RewriteResponseError, GradeResponseError) as exc:
            detail = f"boundary raised {type(exc).__name__}"
            if getattr(exc, "retryable", True):
                return self._retry(
                    listing,
                    stage="resume rewrite",
                    timestamp=timestamp,
                    detail=detail,
                )
            return self._manual(
                listing,
                stage="resume rewrite",
                attempt_number=attempt_number,
                timestamp=timestamp,
                detail=detail,
            )
        except (OSError, ValueError) as exc:
            return self._retry(
                listing,
                stage="resume planning",
                timestamp=timestamp,
                detail=f"raised {type(exc).__name__}",
            )

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
