"""Real fetch-adapter integration with pipeline retry and screening semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from auto_interner.application import ApplicationPipeline
from auto_interner.dedupe import RoleDeduplicator
from auto_interner.demo import FictionalStructuredModel, fictional_base_resume_path
from auto_interner.fetcher import BrowserFetchError, StaticFirstPostingFetcher
from auto_interner.models import Listing, PipelineStatus, PostingFetcher
from auto_interner.network import HttpResponse, NetworkFailure, SafeHttpClient
from auto_interner.paths import OutputPathPlanner
from auto_interner.state_store import StateStore

pytestmark = pytest.mark.integration

NOW = datetime(2027, 1, 2, 3, 4, tzinfo=UTC)


def _pipeline(
    tmp_path: Path,
    fetcher: PostingFetcher,
    *,
    max_attempts: int = 3,
) -> ApplicationPipeline:
    """Drive the real fetch adapter through the shared shadow-mode pipeline."""
    data_dir = tmp_path / "data"
    return ApplicationPipeline(
        state_store=StateStore(tmp_path / "state"),
        fetcher=fetcher,
        model_client=FictionalStructuredModel(),
        output_planner=OutputPathPlanner(data_dir, 2027),
        deduplicator=RoleDeduplicator(data_dir, 2027),
        base_resume_path=fictional_base_resume_path(),
        shadow_mode=True,
        max_attempts=max_attempts,
        clock=lambda: NOW,
    )


def _listing(listing_id: str = "fixture-one") -> Listing:
    return Listing(
        id=listing_id,
        company_name="Fictional Systems",
        title="Software Intern",
        url="https://jobs.example/role",
        locations=("Denver, CO",),
        active=True,
    )


class FakeClient:
    def __init__(self, response: HttpResponse | NetworkFailure) -> None:
        self.response = response

    def get(self, url: str) -> HttpResponse:
        del url
        if isinstance(self.response, NetworkFailure):
            raise self.response
        return self.response


class FailingBrowser:
    def fetch(self, url: str) -> str:
        del url
        raise BrowserFetchError("browser navigation failed")


def test_f_fet_007_and_008_repeated_fetch_failures_become_manual_review(
    tmp_path: Path,
) -> None:
    client = cast(
        SafeHttpClient,
        FakeClient(NetworkFailure("request timed out", retryable=True)),
    )
    fetcher = StaticFirstPostingFetcher(client, browser=FailingBrowser())
    store = StateStore(tmp_path / "state")
    pipeline = _pipeline(tmp_path, fetcher, max_attempts=3)

    first = pipeline.run([_listing()]).outcomes[0]
    second = pipeline.run([_listing()]).outcomes[0]
    third = pipeline.run([_listing()]).outcomes[0]

    assert first.status is second.status is PipelineStatus.RETRYABLE_FAILURE
    assert third.status is PipelineStatus.MANUAL_REVIEW
    assert store.load_seen_ids() == {"fixture-one"}


def test_static_posting_text_flows_into_deterministic_screening(tmp_path: Path) -> None:
    text = (
        "Candidates must be able to obtain and maintain a security clearance. "
        + "Work with a collaborative engineering team on reliable services. " * 5
    )
    response = HttpResponse(
        "https://jobs.example/role",
        200,
        {"content-type": "text/html"},
        f"<main><p>{text}</p></main>".encode(),
    )
    fetcher = StaticFirstPostingFetcher(cast(SafeHttpClient, FakeClient(response)))
    store = StateStore(tmp_path / "state")
    pipeline = _pipeline(tmp_path, fetcher)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.DISQUALIFIED
    assert store.load_seen_ids() == {"fixture-one"}
