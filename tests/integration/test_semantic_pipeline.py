"""Tier 2 integration after deterministic posting screening."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from auto_interner.model_client import ModelBoundaryError
from auto_interner.models import FetchMethod, FetchResult, FetchStatus, Listing, PipelineStatus
from auto_interner.pipeline import OfflinePipeline
from auto_interner.state_store import StateStore

pytestmark = pytest.mark.integration
NOW = datetime(2027, 1, 2, 3, 4, tzinfo=UTC)


def _listing() -> Listing:
    return Listing(
        id="fictional-listing",
        company_name="Fictional Systems",
        title="Software Intern",
        url="https://example.invalid/job",
        locations=("Denver, CO",),
        active=True,
    )


@dataclass
class FakeFetcher:
    text: str

    def fetch(self, listing: Listing, *, attempt_number: int) -> FetchResult:
        return FetchResult(
            listing_id=listing.id,
            status=FetchStatus.SUCCESS,
            attempt_number=attempt_number,
            method=FetchMethod.FIXTURE,
            text=self.text,
        )


@dataclass
class FakeModel:
    result: object
    calls: list[str] = field(default_factory=list)

    def call_tool(
        self,
        *,
        tool_name: str,
        input_schema: dict[str, object],
        system_prompt: str,
        user_prompt: str,
    ) -> object:
        del tool_name, input_schema, system_prompt
        self.calls.append(user_prompt)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _clear() -> dict[str, object]:
    return {
        "drug_testing": {"disqualified": False, "confidence": "low", "evidence": ""},
        "security_clearance": {
            "disqualified": False,
            "confidence": "low",
            "evidence": "",
        },
        "location_is_us": {"confirmed": True, "confidence": "high", "evidence": "US"},
    }


def _pipeline(tmp_path: Path, fetch_text: str, model: FakeModel) -> OfflinePipeline:
    return OfflinePipeline(
        state_store=StateStore(tmp_path / "state"),
        fetcher=FakeFetcher(fetch_text),
        semantic_client=model,
        clock=lambda: NOW,
    )


def test_tier_two_runs_only_after_tier_one_passes(tmp_path: Path) -> None:
    model = FakeModel(_clear())
    pipeline = _pipeline(tmp_path, "A security clearance is required.", model)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.DISQUALIFIED
    assert model.calls == []


def test_semantic_disqualification_is_terminal(tmp_path: Path) -> None:
    payload = _clear()
    drug = payload["drug_testing"]
    assert isinstance(drug, dict)
    drug.update({"disqualified": True, "confidence": "high", "evidence": "test required"})
    pipeline = _pipeline(tmp_path, "A policy applies to this offer.", FakeModel(payload))

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.DISQUALIFIED
    assert StateStore(tmp_path / "state").load_seen_ids() == {"fictional-listing"}


def test_semantic_pass_remains_nonterminal_for_later_stages(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path, "Build reliable Python services.", FakeModel(_clear()))

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.SCREENING_PASSED
    assert not outcome.is_terminal


def test_malformed_semantic_output_retries_without_body_leakage(tmp_path: Path) -> None:
    private_marker = "private-model-body-marker"
    model = FakeModel({"invalid": private_marker})
    pipeline = _pipeline(tmp_path, "Build reliable systems.", model)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.RETRYABLE_FAILURE
    assert private_marker not in StateStore(tmp_path / "state").decisions_path.read_text()


def test_permanent_provider_failure_enters_manual_review(tmp_path: Path) -> None:
    model = FakeModel(ModelBoundaryError("private provider detail", retryable=False))
    pipeline = _pipeline(tmp_path, "Build reliable systems.", model)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.MANUAL_REVIEW
    decision_log = StateStore(tmp_path / "state").decisions_path.read_text()
    assert "private provider detail" not in decision_log
