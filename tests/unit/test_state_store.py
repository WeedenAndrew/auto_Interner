"""F-STA initial state persistence and crash-boundary cases."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from auto_interner.models import Listing, PipelineOutcome, PipelineStatus
from auto_interner.state_store import CommitPoint, StateCorruptionError, StateStore

pytestmark = [pytest.mark.unit, pytest.mark.reliability]

NOW = datetime(2027, 1, 2, 3, 4, tzinfo=UTC)


class InjectedCrash(RuntimeError):
    """Expected test-only interruption."""


class CrashAt:
    def __init__(self, target: CommitPoint) -> None:
        self.target = target
        self.visited: list[CommitPoint] = []

    def trigger(self, point: CommitPoint) -> None:
        self.visited.append(point)
        if point is self.target:
            raise InjectedCrash(point)


def _listing(listing_id: str = "listing-1") -> Listing:
    return Listing(
        id=listing_id,
        company_name="Fictional Systems",
        title="Software Intern",
        url=f"https://example.invalid/{listing_id}",
        locations=("Denver, CO",),
        active=True,
    )


def _terminal(listing_id: str = "listing-1") -> PipelineOutcome:
    return PipelineOutcome(
        listing_id=listing_id,
        status=PipelineStatus.DISQUALIFIED,
        summary="fictional deterministic result",
        timestamp=NOW,
    )


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_f_sta_001_empty_state_loads_empty_collections(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")

    assert store.load_seen_ids() == set()
    assert store.load_retry_counts() == {}


def test_f_sta_002_duplicate_seen_lines_load_once(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.seen_path.write_text("a\na\n\nb\n", encoding="utf-8")

    assert store.load_seen_ids() == {"a", "b"}


def test_invalid_listing_id_cannot_modify_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path)

    with pytest.raises(ValueError, match="listing ID"):
        store.commit_terminal(_terminal("a\nb"))
    assert not store.decisions_path.exists()


def test_f_sta_003_terminal_decision_commits_before_seen_id(tmp_path: Path) -> None:
    injector = CrashAt(CommitPoint.AFTER_DECISION)
    store = StateStore(tmp_path, fault_injector=injector)

    with pytest.raises(InjectedCrash):
        store.commit_terminal(_terminal())

    assert len(_jsonl(store.decisions_path)) == 1
    assert store.load_seen_ids() == set()


def test_f_sta_004_crash_before_decision_keeps_id_unseen(tmp_path: Path) -> None:
    store = StateStore(tmp_path, fault_injector=CrashAt(CommitPoint.BEFORE_DECISION))

    with pytest.raises(InjectedCrash):
        store.commit_terminal(_terminal())

    assert not store.decisions_path.exists()
    assert store.load_seen_ids() == set()


def test_f_sta_005_crash_after_decision_can_safely_reprocess(tmp_path: Path) -> None:
    crashing_store = StateStore(tmp_path, fault_injector=CrashAt(CommitPoint.AFTER_DECISION))
    with pytest.raises(InjectedCrash):
        crashing_store.commit_terminal(_terminal())

    recovered_store = StateStore(tmp_path)
    assert recovered_store.commit_terminal(_terminal()) is True
    assert recovered_store.load_seen_ids() == {"listing-1"}
    assert len(_jsonl(recovered_store.decisions_path)) == 1


def test_f_sta_006_crash_after_seen_leaves_recoverable_terminal_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path, fault_injector=CrashAt(CommitPoint.AFTER_SEEN))

    with pytest.raises(InjectedCrash):
        store.commit_terminal(_terminal())

    recovered_store = StateStore(tmp_path)
    assert recovered_store.load_seen_ids() == {"listing-1"}
    assert recovered_store.commit_terminal(_terminal()) is False
    assert len(_jsonl(recovered_store.decisions_path)) == 1


def test_nonterminal_outcome_cannot_use_terminal_commit(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    outcome = PipelineOutcome(
        listing_id="one",
        status=PipelineStatus.SHADOW_READY,
        summary="later stages pending",
        timestamp=NOW,
    )

    with pytest.raises(ValueError, match="only terminal"):
        store.commit_terminal(outcome)
    store.record_outcome(outcome)
    assert store.load_seen_ids() == set()


def test_terminal_outcome_cannot_use_nonterminal_writer(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="terminal outcomes"):
        StateStore(tmp_path).record_outcome(_terminal())


def test_f_sta_007_retry_increments_without_seen_append(tmp_path: Path) -> None:
    store = StateStore(tmp_path)

    outcome = store.record_retry(
        _listing(), reason=" fixture   timeout ", max_attempts=3, timestamp=NOW
    )

    assert outcome.status is PipelineStatus.RETRYABLE_FAILURE
    assert outcome.summary == "fixture timeout"
    assert store.load_retry_counts() == {"listing-1": 1}
    assert store.load_seen_ids() == set()


def test_f_sta_008_third_retry_enters_manual_review_and_seen_set(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    listing = _listing()

    first = store.record_retry(listing, reason="timeout", max_attempts=3, timestamp=NOW)
    second = store.record_retry(listing, reason="timeout", max_attempts=3, timestamp=NOW)
    third = store.record_retry(listing, reason="timeout", max_attempts=3, timestamp=NOW)

    assert first.status is second.status is PipelineStatus.RETRYABLE_FAILURE
    assert third.status is PipelineStatus.MANUAL_REVIEW
    assert store.load_seen_ids() == {listing.id}
    assert store.load_retry_counts() == {}
    assert _jsonl(store.manual_review_path)[0]["listing_id"] == listing.id


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"listing-1": -1}', '{"listing-1": true}', '{"": 1}'],
)
def test_f_sta_010_corrupt_retry_state_is_never_discarded(tmp_path: Path, content: str) -> None:
    store = StateStore(tmp_path)
    store.retry_path.write_text(content, encoding="utf-8")

    with pytest.raises(StateCorruptionError):
        store.load_retry_counts()
    assert store.retry_path.read_text(encoding="utf-8") == content


def test_clear_retry_count_removes_only_requested_listing(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.record_retry(_listing("a"), reason="timeout", max_attempts=3, timestamp=NOW)
    store.record_retry(_listing("b"), reason="timeout", max_attempts=3, timestamp=NOW)

    store.clear_retry_count("a")
    store.clear_retry_count("missing")

    assert store.load_retry_counts() == {"b": 1}


def test_run_summary_heartbeat_and_manual_review_count(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.record_run_summary({"run_id": "fixture", "complete": True})
    store.write_heartbeat({"status": "idle", "run_id": "fixture"})
    assert store.manual_review_count() == 0

    store.send_to_manual_review(_listing(), reason="fixture", attempt_number=1, timestamp=NOW)
    store.send_to_manual_review(_listing(), reason="fixture", attempt_number=1, timestamp=NOW)

    assert _jsonl(store.run_summary_path) == [{"complete": True, "run_id": "fixture"}]
    assert json.loads(store.heartbeat_path.read_text(encoding="utf-8"))["status"] == "idle"
    assert store.manual_review_count() == 1


def test_reconciliation_reports_recoverable_decision_commit_gap(tmp_path: Path) -> None:
    crashing = StateStore(tmp_path, fault_injector=CrashAt(CommitPoint.AFTER_DECISION))
    with pytest.raises(InjectedCrash):
        crashing.commit_terminal(_terminal())

    report = StateStore(tmp_path).reconcile()

    assert report.seen_ids == 0
    assert report.terminal_decisions == 1
    assert report.terminal_awaiting_seen == 1


def test_reconciliation_rejects_seen_id_without_terminal_decision(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.seen_path.write_text("orphan\n", encoding="utf-8")

    with pytest.raises(StateCorruptionError, match="without terminal"):
        store.reconcile()
