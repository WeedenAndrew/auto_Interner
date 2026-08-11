"""Typed domain records and boundary protocols shared by the pipeline."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class FetchStatus(StrEnum):
    """Result classes returned by a posting fetch adapter."""

    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"


class FetchMethod(StrEnum):
    """Mechanism that produced usable posting text."""

    STATIC = "static"
    BROWSER = "browser"
    FIXTURE = "fixture"


class ScreeningTier(StrEnum):
    """Screening stage that produced evidence."""

    STRUCTURED_LOCATION = "tier_0_location"
    DETERMINISTIC_TEXT = "tier_1_text"
    SEMANTIC = "tier_2_semantic"


class ScreeningCategory(StrEnum):
    """Candidate-specific hard-disqualifier categories."""

    LOCATION = "location"
    DRUG_TESTING = "drug_testing"
    SECURITY_CLEARANCE = "security_clearance"


class EvidenceDecision(StrEnum):
    """Meaning of one screening evidence record."""

    PASS = "pass"
    DISQUALIFY = "disqualify"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    """Confidence attached to a screening observation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScreeningOutcome(StrEnum):
    """Combined result of the deterministic screening stages."""

    PASS = "pass"
    DISQUALIFY = "disqualify"


class PipelineStatus(StrEnum):
    """Outcomes available to the staged pipeline."""

    DISQUALIFIED = "disqualified"
    DEDUPE_SKIPPED = "dedupe_skipped"
    SHADOW_READY = "shadow_ready"
    RESUME_GENERATED = "resume_generated"
    RETRYABLE_FAILURE = "retryable_failure"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True, slots=True)
class Listing:
    """Validated listing data used by domain modules."""

    id: str
    company_name: str
    title: str
    url: str
    locations: tuple[str, ...]
    active: bool
    source: str | None = None
    date_posted: str | None = None
    date_updated: str | None = None
    sponsorship: str | None = None
    metadata: dict[str, object] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Posting fetch result with no exception or body leakage requirement."""

    listing_id: str
    status: FetchStatus
    attempt_number: int
    method: FetchMethod | None = None
    text: str = ""
    failure_reason: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ScreeningEvidence:
    """Short, non-sensitive explanation of one deterministic decision."""

    category: ScreeningCategory
    decision: EvidenceDecision
    confidence: Confidence
    tier: ScreeningTier
    evidence: str


@dataclass(frozen=True, slots=True)
class ScreeningDecision:
    """Deterministic screening decision for one listing."""

    listing_id: str
    outcome: ScreeningOutcome
    evidence: tuple[ScreeningEvidence, ...]
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """State-store input produced by pipeline orchestration."""

    listing_id: str
    status: PipelineStatus
    summary: str
    timestamp: datetime
    decision: ScreeningDecision | None = None
    output_path: Path | None = None
    attempt_number: int | None = None

    @property
    def is_terminal(self) -> bool:
        """Return whether the listing can safely join the seen-ID set."""
        return self.status in {
            PipelineStatus.DISQUALIFIED,
            PipelineStatus.DEDUPE_SKIPPED,
            PipelineStatus.RESUME_GENERATED,
            PipelineStatus.MANUAL_REVIEW,
        }


@dataclass(frozen=True, slots=True)
class PipelineRunResult:
    """Deterministic summary of one complete pipeline run."""

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


class PostingFetcher(Protocol):
    """Replaceable posting-text acquisition boundary."""

    def fetch(self, listing: Listing, *, attempt_number: int) -> FetchResult:
        """Return one classified fetch result without writing state."""
