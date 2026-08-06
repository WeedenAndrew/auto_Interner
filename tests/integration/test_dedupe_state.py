"""Phase 3 deduplication integrates with the existing terminal state boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from auto_interner.dedupe import RoleDeduplicator
from auto_interner.models import Listing, PipelineOutcome, PipelineStatus
from auto_interner.paths import OutputPathPlanner
from auto_interner.state_store import StateStore

pytestmark = pytest.mark.integration


def _listing(listing_id: str) -> Listing:
    return Listing(
        id=listing_id,
        company_name="Fictional Systems",
        title="Software Engineer Intern",
        url=f"https://example.invalid/jobs/{listing_id}",
        locations=("Denver, CO",),
        active=True,
    )


def test_duplicate_result_can_commit_through_the_single_terminal_state_owner(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    existing = _listing("fixture-existing")
    planner = OutputPathPlanner(data_dir, 2027)
    existing_plan = planner.plan(
        existing,
        generated_at=datetime(2027, 7, 1, 9, tzinfo=UTC),
    )
    planner.prepare(existing_plan).write_bytes(b"fictional generated document placeholder")
    current = _listing("fixture-current")
    timestamp = datetime(2027, 8, 31, 12, tzinfo=UTC)

    dedupe = RoleDeduplicator(data_dir, 2027).check(current, as_of=timestamp)
    assert dedupe.is_duplicate is True
    outcome = PipelineOutcome(
        listing_id=current.id,
        status=PipelineStatus.DEDUPE_SKIPPED,
        summary="same company and normalized role was generated within six calendar months",
        timestamp=timestamp,
    )
    store = StateStore(tmp_path / "state")

    assert store.commit_terminal(outcome) is True
    assert current.id in store.load_seen_ids()
