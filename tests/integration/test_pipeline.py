"""Integration coverage for the complete offline listing-to-decision slice."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from auto_interner.models import (
    FetchMethod,
    FetchResult,
    FetchStatus,
    Listing,
    PipelineStatus,
)
from auto_interner.pipeline import OfflinePipeline
from auto_interner.state_store import StateStore

pytestmark = pytest.mark.integration

NOW = datetime(2027, 1, 2, 3, 4, tzinfo=UTC)


class FakeFetcher:
    def __init__(self, results: dict[str, tuple[FetchStatus, str]]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def fetch(self, listing: Listing, *, attempt_number: int) -> FetchResult:
        self.calls.append((listing.id, attempt_number))
        status, value = self.results[listing.id]
        if status is FetchStatus.SUCCESS:
            return FetchResult(
                listing_id=listing.id,
                status=status,
                attempt_number=attempt_number,
                method=FetchMethod.FIXTURE,
                text=value,
            )
        return FetchResult(
            listing_id=listing.id,
            status=status,
            attempt_number=attempt_number,
            failure_reason=value,
        )


def _listing(listing_id: str, location: str, *, active: bool = True) -> Listing:
    return Listing(
        id=listing_id,
        company_name="Fictional Systems",
        title="Software Intern",
        url=f"https://example.invalid/{listing_id}",
        locations=(location,),
        active=active,
    )


def _pipeline(tmp_path: Path, fetcher: FakeFetcher, *, max_attempts: int = 3) -> OfflinePipeline:
    return OfflinePipeline(
        state_store=StateStore(tmp_path / "state"),
        fetcher=fetcher,
        window_size=2,
        max_fetch_attempts=max_attempts,
        clock=lambda: NOW,
    )


def test_offline_pipeline_routes_each_deterministic_outcome(tmp_path: Path) -> None:
    listings = [
        _listing("location", "Toronto, Canada"),
        _listing("keyword", "Denver, CO"),
        _listing("pass", "Distributed"),
        _listing("retry", "Austin, TX"),
        _listing("inactive", "Seattle, WA", active=False),
    ]
    fetcher = FakeFetcher(
        {
            "keyword": (FetchStatus.SUCCESS, "An active security clearance is required."),
            "pass": (FetchStatus.SUCCESS, "Build reliable services with Python."),
            "retry": (FetchStatus.RETRYABLE_FAILURE, "fixture timeout"),
        }
    )

    result = _pipeline(tmp_path, fetcher).run(listings)

    assert result.as_dict() == {
        "source_records": 5,
        "active_records": 4,
        "skipped_seen": 0,
        "windows_processed": 2,
        "processed": 4,
        "terminal": 2,
        "status_counts": {
            "disqualified": 2,
            "screening_passed": 1,
            "retryable_failure": 1,
        },
    }
    assert fetcher.calls == [("keyword", 1), ("pass", 1), ("retry", 1)]
    assert StateStore(tmp_path / "state").load_seen_ids() == {"location", "keyword"}


def test_second_run_skips_only_terminal_outcomes(tmp_path: Path) -> None:
    listings = [
        _listing("location", "Toronto, Canada"),
        _listing("keyword", "Denver, CO"),
        _listing("pass", "Remote in US"),
    ]
    fetcher = FakeFetcher(
        {
            "keyword": (FetchStatus.SUCCESS, "A security clearance is required."),
            "pass": (FetchStatus.SUCCESS, "Build APIs and tests."),
        }
    )
    pipeline = _pipeline(tmp_path, fetcher)

    first = pipeline.run(listings)
    second = pipeline.run(listings)

    assert [outcome.status for outcome in first.outcomes] == [
        PipelineStatus.DISQUALIFIED,
        PipelineStatus.DISQUALIFIED,
        PipelineStatus.SCREENING_PASSED,
    ]
    assert [outcome.status for outcome in second.outcomes] == [PipelineStatus.SCREENING_PASSED]
    assert second.skipped_seen == 2
    assert fetcher.calls == [("keyword", 1), ("pass", 1), ("pass", 1)]


def test_fetch_exceptions_retry_then_become_manual_review(tmp_path: Path) -> None:
    class RaisingFetcher:
        def fetch(self, listing: Listing, *, attempt_number: int) -> FetchResult:
            del listing, attempt_number
            raise TimeoutError("private boundary detail is not persisted")

    listing = _listing("unstable", "Denver, CO")
    store = StateStore(tmp_path / "state")
    pipeline = OfflinePipeline(
        state_store=store,
        fetcher=RaisingFetcher(),
        max_fetch_attempts=2,
        clock=lambda: NOW,
    )

    first = pipeline.run([listing])
    second = pipeline.run([listing])

    assert first.outcomes[0].status is PipelineStatus.RETRYABLE_FAILURE
    assert second.outcomes[0].status is PipelineStatus.MANUAL_REVIEW
    assert store.load_seen_ids() == {listing.id}
    assert "private boundary detail" not in store.decisions_path.read_text(encoding="utf-8")


def test_permanent_or_invalid_fetch_result_enters_manual_review(tmp_path: Path) -> None:
    fetcher = FakeFetcher({"missing": (FetchStatus.PERMANENT_FAILURE, "fixture missing")})

    outcome = _pipeline(tmp_path, fetcher).run([_listing("missing", "Denver, CO")]).outcomes[0]

    assert outcome.status is PipelineStatus.MANUAL_REVIEW
    assert outcome.is_terminal
