"""Tier 2 verdict reuse, expiry, and drift policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from auto_interner.screening.semantic_cache import (
    MAX_AGE,
    CachedVerdict,
    plan_lookup,
    resolve_disagreement,
)
from auto_interner.state_store import StateStore

pytestmark = [pytest.mark.unit]

NOW = datetime(2026, 8, 19, 12, tzinfo=UTC)


def _verdict(*, disqualified: bool = False, age: timedelta = timedelta(0)) -> CachedVerdict:
    return CachedVerdict(
        disqualified=disqualified,
        screened_at=NOW - age,
        summary="fictional evidence",
        category="drug_testing" if disqualified else "",
    )


def test_no_cached_verdict_means_screen() -> None:
    plan = plan_lookup(None, now=NOW)
    assert plan.screen_again is True
    assert plan.reuse is None


def test_a_fresh_verdict_is_reused_without_screening() -> None:
    plan = plan_lookup(_verdict(age=timedelta(days=6)), now=NOW)
    assert plan.screen_again is False
    assert plan.reuse is not None


def test_a_verdict_past_the_age_limit_is_rescreened() -> None:
    """One week is the operator's stated floor for drift checking."""
    plan = plan_lookup(_verdict(age=MAX_AGE + timedelta(seconds=1)), now=NOW)
    assert plan.screen_again is True
    assert plan.reuse is not None  # still carried, so disagreement can be detected


def test_agreement_acts_on_the_verdict_and_reports_no_drift() -> None:
    acted, drift = resolve_disagreement(_verdict(disqualified=True), fresh_disqualified=True)
    assert acted is True
    assert drift is None


@pytest.mark.parametrize("cached_disqualified", [True, False])
def test_a_disagreement_never_disqualifies(cached_disqualified: bool) -> None:
    """In either direction. A disqualification is terminal and cannot be undone."""
    acted, drift = resolve_disagreement(
        _verdict(disqualified=cached_disqualified),
        fresh_disqualified=not cached_disqualified,
    )
    assert acted is False
    assert drift is not None and "drift" in drift


def test_a_verdict_survives_a_write_and_read(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.record_semantic_verdict("hash-1", _verdict(disqualified=True))

    loaded = store.load_semantic_cache()["hash-1"]
    assert loaded.disqualified is True
    assert loaded.screened_at == NOW
    assert loaded.category == "drug_testing"


def test_an_unreadable_cache_is_dropped_rather_than_raised(tmp_path: Path) -> None:
    """Losing a cached verdict costs one screen; refusing to start costs the run."""
    store = StateStore(tmp_path / "state")
    store.state_dir.mkdir(parents=True, exist_ok=True)
    store.semantic_cache_path.write_text("{ not json", encoding="utf-8")

    assert store.load_semantic_cache() == {}


def test_the_cache_is_bounded_and_evicts_the_oldest(tmp_path: Path) -> None:
    """A six-month unattended run would otherwise grow this file without bound."""
    store = StateStore(tmp_path / "state")
    for index in range(5):
        store.record_semantic_verdict(
            f"hash-{index}", _verdict(age=timedelta(days=index)), max_entries=3
        )

    remaining = store.load_semantic_cache()
    assert len(remaining) == 3
    assert set(remaining) == {"hash-0", "hash-1", "hash-2"}


def test_drift_is_recorded_where_an_operator_can_find_it(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.record_semantic_drift("listing-1", "tier 2 drift: cached True, fresh False")

    assert "listing-1" in store.drift_path.read_text(encoding="utf-8")
