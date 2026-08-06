"""Reproducible offline demonstration with fictional source and posting data."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import cast

from auto_interner.models import FetchMethod, FetchResult, FetchStatus, Listing
from auto_interner.pipeline import OfflinePipeline, PipelineRunResult
from auto_interner.source import SnapshotResult, parse_snapshot_json
from auto_interner.state_store import StateStore


class DemoDataError(ValueError):
    """Raised when a bundled demonstration fixture is invalid."""


class FixtureFetcher:
    """Posting fetch adapter backed only by bundled fictional JSON."""

    def __init__(self, entries: dict[str, dict[str, str]]) -> None:
        self._entries = entries
        self.calls: list[str] = []

    def fetch(self, listing: Listing, *, attempt_number: int) -> FetchResult:
        """Return a configured result without network or browser access."""
        self.calls.append(listing.id)
        entry = self._entries.get(listing.id)
        if entry is None:
            return FetchResult(
                listing_id=listing.id,
                status=FetchStatus.PERMANENT_FAILURE,
                attempt_number=attempt_number,
                failure_reason="fixture posting is missing",
            )

        try:
            status = FetchStatus(entry["status"])
        except (KeyError, ValueError) as exc:
            raise DemoDataError(f"invalid fetch status for fixture {listing.id}") from exc
        if status is FetchStatus.SUCCESS:
            return FetchResult(
                listing_id=listing.id,
                status=status,
                attempt_number=attempt_number,
                method=FetchMethod.FIXTURE,
                text=entry.get("text", ""),
            )
        return FetchResult(
            listing_id=listing.id,
            status=status,
            attempt_number=attempt_number,
            failure_reason=entry.get("failure_reason", "fixture fetch failed"),
        )


def _read_asset(name: str) -> str:
    return resources.files("auto_interner.demo_data").joinpath(name).read_text(encoding="utf-8")


def load_demo_snapshot() -> SnapshotResult:
    """Load the bundled fictional listing snapshot."""
    return parse_snapshot_json(_read_asset("listings.json"))


def load_demo_fetcher() -> FixtureFetcher:
    """Load and validate the bundled fictional posting results."""
    try:
        payload = cast(object, json.loads(_read_asset("postings.json")))
    except json.JSONDecodeError as exc:
        raise DemoDataError("posting fixtures contain invalid JSON") from exc
    if not isinstance(payload, dict):
        raise DemoDataError("posting fixtures must be a JSON object")

    entries: dict[str, dict[str, str]] = {}
    for listing_id, raw_entry in cast(dict[object, object], payload).items():
        if not isinstance(listing_id, str) or not isinstance(raw_entry, dict):
            raise DemoDataError("posting fixture entries must be string-keyed objects")
        entry = cast(dict[object, object], raw_entry)
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in entry.items()):
            raise DemoDataError("posting fixture fields must be strings")
        entries[listing_id] = {cast(str, key): cast(str, value) for key, value in entry.items()}
    return FixtureFetcher(entries)


def run_demo(
    state_dir: Path,
    *,
    window_size: int = 2,
    max_fetch_attempts: int = 3,
) -> tuple[PipelineRunResult, SnapshotResult, FixtureFetcher]:
    """Run the complete Phase 1 slice without reading private configuration."""
    snapshot = load_demo_snapshot()
    fetcher = load_demo_fetcher()
    pipeline = OfflinePipeline(
        state_store=StateStore(state_dir),
        fetcher=fetcher,
        window_size=window_size,
        max_fetch_attempts=max_fetch_attempts,
    )
    result = pipeline.run(snapshot.listings)
    return result, snapshot, fetcher
