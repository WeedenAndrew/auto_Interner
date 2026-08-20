"""Explicit runtime composition for live and fully fictional workflows."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from auto_interner.application import ApplicationPipeline
from auto_interner.config import Settings
from auto_interner.dedupe import RoleDeduplicator
from auto_interner.demo import (
    FictionalStructuredModel,
    FixtureFetcher,
    fictional_base_resume_path,
)
from auto_interner.fetcher import (
    SeleniumBrowserFetcher,
    SeleniumChromeFactory,
    StaticFirstPostingFetcher,
)
from auto_interner.model_client import AnthropicMessagesClient, StructuredModelClient
from auto_interner.models import Listing, PostingFetcher
from auto_interner.network import SafeHttpClient
from auto_interner.paths import OutputPathPlanner
from auto_interner.runtime import (
    GitRuntimeSource,
    HttpRuntimeSource,
    RunCoordinator,
    RuntimeSource,
)
from auto_interner.sources import (
    GitSnapshotLoader,
    RemoteSnapshotLoader,
    SnapshotDownload,
    SnapshotResult,
)
from auto_interner.state_store import StateStore

_FIXTURE_VERSION = "fictional-full-pipeline-v1"
_FIXTURE_POSTING = (
    "Fictional Systems seeks a software engineering intern to build reliable Python services, "
    "write tests, review code, document decisions, and collaborate with a small engineering "
    "team. This invented role is located in Denver, Colorado, and contains no real employer or "
    "applicant data. Candidates learn through scoped projects and human-reviewed deliverables."
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FixtureRuntimeSource:
    """One stable fictional source with the same processed-marker semantics as Git."""

    def __init__(self, state_dir: Path, download: SnapshotDownload) -> None:
        self._marker_path = state_dir / "fixture_source_version.txt"
        self._download = download

    def acquire(self) -> SnapshotDownload | None:
        if (
            self._marker_path.exists()
            and self._marker_path.read_text(encoding="utf-8").strip() == _FIXTURE_VERSION
        ):
            return None
        return self._download

    def mark_processed(self, source_version: str) -> None:
        if source_version != _FIXTURE_VERSION:
            raise ValueError("fixture source version is invalid")
        self._marker_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._marker_path.parent,
            prefix=f".{self._marker_path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(f"{source_version}\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._marker_path)
        finally:
            temporary_path.unlink(missing_ok=True)


def _build_pipeline(
    *,
    settings: Settings,
    source: RuntimeSource,
    state_store: StateStore,
    fetcher: PostingFetcher,
    model_client: StructuredModelClient,
    base_resume_path: Path,
    clock: Callable[[], datetime] = _utc_now,
) -> RunCoordinator:
    pipeline = ApplicationPipeline(
        state_store=state_store,
        fetcher=fetcher,
        model_client=model_client,
        output_planner=OutputPathPlanner(settings.data_dir, settings.recruiting_year),
        deduplicator=RoleDeduplicator(settings.data_dir, settings.recruiting_year),
        base_resume_path=base_resume_path,
        shadow_mode=settings.shadow_mode,
        recruiting_year=settings.recruiting_year,
        window_size=settings.window_size,
        max_attempts=settings.max_fetch_attempts,
        clock=clock,
    )
    return RunCoordinator(
        source=source,
        pipeline=pipeline,
        state_store=state_store,
        clock=clock,
    )


def build_live_coordinator(settings: Settings) -> RunCoordinator:
    """Compose a live run only after explicit configuration validation."""
    settings.ensure_runtime_layout()
    settings.validate_runtime_requirements(require_model_key=True, require_base_resume=True)
    if settings.anthropic_api_key is None:  # pragma: no cover - validated immediately above
        raise AssertionError("validated model key is absent")
    state_store = StateStore(settings.state_dir)
    posting_client = SafeHttpClient(timeout_seconds=settings.static_fetch_timeout_seconds)
    browser = None
    if settings.browser_enabled:
        browser = SeleniumBrowserFetcher(
            SeleniumChromeFactory(
                chromium_binary=settings.chromium_binary,
                chromedriver_path=settings.chromedriver_path,
                no_sandbox=settings.browser_no_sandbox,
            ),
            timeout_seconds=settings.browser_fetch_timeout_seconds,
        )
    fetcher = StaticFirstPostingFetcher(posting_client, browser=browser)
    model_client = AnthropicMessagesClient(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
    )
    if settings.listings_source_mode == "git":
        source: RuntimeSource = GitRuntimeSource(
            GitSnapshotLoader(
                repository_url=settings.source_repository_url,
                branch_ref=settings.listings_git_ref,
                snapshot_path=settings.listings_git_path,
                cache_dir=settings.source_cache_dir,
                timeout_seconds=settings.git_fetch_timeout_seconds,
            )
        )
    else:
        source = HttpRuntimeSource(
            RemoteSnapshotLoader(
                SafeHttpClient(
                    timeout_seconds=settings.static_fetch_timeout_seconds,
                    max_response_bytes=20 * 1024 * 1024,
                )
            ),
            settings.source_url,
        )
    return _build_pipeline(
        settings=settings,
        source=source,
        state_store=state_store,
        fetcher=fetcher,
        model_client=model_client,
        base_resume_path=settings.base_resume_path,
    )


def build_fixture_coordinator(
    *,
    data_dir: Path,
    state_dir: Path,
    write: bool,
    recruiting_year: int = 2027,
    clock: Callable[[], datetime] = _utc_now,
) -> RunCoordinator:
    """Compose a complete fictional run without configuration, secrets, or network calls."""
    listing = Listing(
        id="fictional-full-pipeline-1",
        company_name="Fictional Systems",
        title="Software Engineering Intern",
        url="https://example.invalid/fictional-full-pipeline-1",
        locations=("Denver, CO",),
        active=True,
        source="bundled-fictional-fixture",
    )
    snapshot = SnapshotResult((listing,), ())
    body = _FIXTURE_POSTING.encode("utf-8")
    download = SnapshotDownload(
        snapshot=snapshot,
        content_hash=sha256(body).hexdigest(),
        content_length=len(body),
        source_version=_FIXTURE_VERSION,
        changed_since_last_success=True,
    )
    settings = Settings(
        recruiting_year=recruiting_year,
        listings_source_mode="git",
        listings_url=None,
        listings_url_template=None,
        listings_git_repository="https://github.com/SimplifyJobs/Summer2027-Internships.git",
        listings_git_repository_template=None,
        listings_git_ref="refs/heads/dev",
        listings_git_path=".github/scripts/listings.json",
        poll_interval_hours=2.0,
        window_size=100,
        static_fetch_timeout_seconds=15.0,
        git_fetch_timeout_seconds=60.0,
        browser_fetch_timeout_seconds=35.0,
        max_fetch_attempts=3,
        anthropic_model="fictional-model",
        anthropic_api_key=None,
        shadow_mode=not write,
        data_dir=data_dir,
        state_dir=state_dir,
        log_level="INFO",
    )
    base_resume = fictional_base_resume_path()
    state_store = StateStore(state_dir)
    return _build_pipeline(
        settings=settings,
        source=FixtureRuntimeSource(state_dir, download),
        state_store=state_store,
        fetcher=FixtureFetcher({listing.id: {"status": "success", "text": _FIXTURE_POSTING}}),
        model_client=FictionalStructuredModel(),
        base_resume_path=base_resume,
        clock=clock,
    )
