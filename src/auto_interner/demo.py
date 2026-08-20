"""Reproducible offline fixtures and the bundled fictional demonstration run."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import cast

from auto_interner.application import ApplicationPipeline
from auto_interner.dedupe import RoleDeduplicator
from auto_interner.models import (
    FetchMethod,
    FetchResult,
    FetchStatus,
    Listing,
    PipelineRunResult,
)
from auto_interner.paths import OutputPathPlanner
from auto_interner.rewriting.service import REWRITE_TOOL_NAME
from auto_interner.screening.semantic import SEMANTIC_TOOL_NAME
from auto_interner.sources import SnapshotResult, parse_snapshot_json
from auto_interner.state_store import StateStore

DEMO_RECRUITING_YEAR = 2027


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
            text = entry.get("text", "")
            return FetchResult(
                listing_id=listing.id,
                status=status,
                attempt_number=attempt_number,
                method=FetchMethod.FIXTURE,
                text=text,
                # The real adapters hash the body they return, and the Tier 2
                # cache is keyed on it. Omitting it here left the fixture path
                # silently unable to reach the cache at all.
                content_hash=sha256(text.encode("utf-8")).hexdigest(),
            )
        return FetchResult(
            listing_id=listing.id,
            status=status,
            attempt_number=attempt_number,
            failure_reason=entry.get("failure_reason", "fixture fetch failed"),
        )


class FictionalStructuredModel:
    """Deterministic model fake covering both tool boundaries with no network."""

    def call_tool(
        self,
        *,
        tool_name: str,
        input_schema: Mapping[str, object],
        system_prompt: str,
        user_prompt: str,
    ) -> object:
        del input_schema, system_prompt
        if tool_name == SEMANTIC_TOOL_NAME:
            return {
                "drug_testing": {
                    "disqualified": False,
                    "confidence": "high",
                    "evidence": "no requirement appears in the fictional posting",
                },
                "security_clearance": {
                    "disqualified": False,
                    "confidence": "high",
                    "evidence": "no clearance appears in the fictional posting",
                },
                "location_is_us": {
                    "confirmed": True,
                    "confidence": "high",
                    "evidence": "the fictional posting states a United States location",
                },
            }
        if tool_name != REWRITE_TOOL_NAME:
            raise ValueError("fixture model received an unknown tool")
        payload = cast(object, json.loads(user_prompt))
        if not isinstance(payload, dict) or not isinstance(payload.get("base_resume"), dict):
            raise ValueError("fixture rewrite payload is invalid")
        base_resume = cast(dict[str, object], payload["base_resume"])
        raw_sections = base_resume.get("sections")
        if not isinstance(raw_sections, list):
            raise ValueError("fixture rewrite payload omitted sections")
        names = [
            section["name"]
            for section in raw_sections
            if isinstance(section, dict) and isinstance(section.get("name"), str)
        ]
        if len(names) != len(raw_sections):
            raise ValueError("fixture rewrite payload contains an invalid section")
        preferred = [name for name in names if cast(str, name).casefold() == "technical skills"]
        remaining = [name for name in names if name not in preferred]
        return {"section_order": [*preferred, *remaining], "replacements": []}


def _read_asset(name: str) -> str:
    return resources.files("auto_interner.demo_data").joinpath(name).read_text(encoding="utf-8")


def fictional_base_resume_path() -> Path:
    """Return the bundled fictional base resume used by every offline run."""
    return Path(
        str(resources.files("auto_interner.demo_data").joinpath("fictional_base_resume.docx"))
    )


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


def _utc_now() -> datetime:
    return datetime.now(UTC)


def run_demo(
    state_dir: Path,
    *,
    window_size: int = 2,
    max_fetch_attempts: int = 3,
    clock: Callable[[], datetime] = _utc_now,
) -> tuple[PipelineRunResult, SnapshotResult, FixtureFetcher]:
    """Run the complete pipeline on bundled fictional data without private inputs.

    The demonstration is always a shadow run, so the derived data directory under
    ``state_dir`` describes intended output paths but is never written to.
    """
    snapshot = load_demo_snapshot()
    fetcher = load_demo_fetcher()
    data_dir = state_dir / "demo-data"
    pipeline = ApplicationPipeline(
        state_store=StateStore(state_dir),
        fetcher=fetcher,
        model_client=FictionalStructuredModel(),
        output_planner=OutputPathPlanner(data_dir, DEMO_RECRUITING_YEAR),
        deduplicator=RoleDeduplicator(data_dir, DEMO_RECRUITING_YEAR),
        base_resume_path=fictional_base_resume_path(),
        shadow_mode=True,
        recruiting_year=DEMO_RECRUITING_YEAR,
        window_size=window_size,
        max_attempts=max_fetch_attempts,
        clock=clock,
    )
    result = pipeline.run(snapshot.listings)
    return result, snapshot, fetcher
