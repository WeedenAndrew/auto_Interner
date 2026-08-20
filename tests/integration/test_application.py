"""F-ORC complete application-pipeline integration cases."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import cast

import pytest

from auto_interner.application import ApplicationPipeline
from auto_interner.dedupe import RoleDeduplicator
from auto_interner.demo import FixtureFetcher
from auto_interner.model_client import ModelBoundaryError
from auto_interner.models import FetchResult, Listing, PipelineStatus
from auto_interner.paths import OutputPathPlanner
from auto_interner.rewriting.service import REWRITE_TOOL_NAME, RewriteResponseError
from auto_interner.screening.semantic import SEMANTIC_TOOL_NAME
from auto_interner.state_store import StateStore

pytestmark = pytest.mark.integration

NOW = datetime(2027, 1, 2, 3, 4, tzinfo=UTC)
POSTING = (
    "This fictional software engineering internship builds reliable Python services, writes "
    "automated tests, documents decisions, and collaborates with a small engineering team in "
    "Denver, Colorado. The text is intentionally long enough to represent a usable posting."
)


class FakeModel:
    def __init__(self, *, semantic: object | None = None, rewrite: object | None = None) -> None:
        self.semantic = semantic
        self.rewrite = rewrite
        self.calls: list[str] = []

    def call_tool(
        self,
        *,
        tool_name: str,
        input_schema: object,
        system_prompt: str,
        user_prompt: str,
    ) -> object:
        del input_schema, system_prompt
        self.calls.append(tool_name)
        if tool_name == SEMANTIC_TOOL_NAME:
            return self.semantic or {
                "drug_testing": {
                    "disqualified": False,
                    "confidence": "high",
                    "evidence": "none stated",
                },
                "security_clearance": {
                    "disqualified": False,
                    "confidence": "high",
                    "evidence": "none stated",
                },
                "location_is_us": {
                    "confirmed": True,
                    "confidence": "high",
                    "evidence": "Denver, Colorado",
                },
            }
        if self.rewrite is not None:
            return self.rewrite
        payload = json.loads(user_prompt)
        sections = payload["base_resume"]["sections"]
        names = [section["name"] for section in sections]
        return {"section_order": names, "replacements": []}


def _listing(listing_id: str = "fictional-1") -> Listing:
    return Listing(
        id=listing_id,
        company_name="Fictional Systems",
        title="Software Engineering Intern",
        url=f"https://example.invalid/{listing_id}",
        locations=("Denver, CO",),
        active=True,
    )


def _base_resume() -> Path:
    return Path(
        str(resources.files("auto_interner.demo_data").joinpath("fictional_base_resume.docx"))
    )


def _pipeline(
    tmp_path: Path,
    *,
    shadow: bool,
    model: FakeModel | None = None,
    fetcher: FixtureFetcher | None = None,
    window_size: int = 10,
    max_attempts: int = 3,
) -> tuple[ApplicationPipeline, StateStore, FixtureFetcher, FakeModel]:
    data_dir = tmp_path / "data"
    state = StateStore(tmp_path / "state")
    resolved_fetcher = fetcher or FixtureFetcher(
        {_listing().id: {"status": "success", "text": POSTING}}
    )
    resolved_model = model or FakeModel()
    return (
        ApplicationPipeline(
            state_store=state,
            fetcher=resolved_fetcher,
            model_client=resolved_model,
            output_planner=OutputPathPlanner(data_dir, 2027),
            deduplicator=RoleDeduplicator(data_dir, 2027),
            base_resume_path=_base_resume(),
            shadow_mode=shadow,
            recruiting_year=2027,
            window_size=window_size,
            max_attempts=max_attempts,
            clock=lambda: NOW,
        ),
        state,
        resolved_fetcher,
        resolved_model,
    )


def test_f_orc_001_generates_company_role_date_document(tmp_path: Path) -> None:
    pipeline, state, _fetcher, model = _pipeline(tmp_path, shadow=False)

    result = pipeline.run([_listing()])

    outcome = result.outcomes[0]
    expected = (
        tmp_path / "data" / "2027" / "fictional-systems" / "engineering-software_01-02-27.docx"
    )
    assert outcome.status is PipelineStatus.RESUME_GENERATED
    assert outcome.output_path == expected
    assert expected.is_file()
    assert state.load_seen_ids() == {"fictional-1"}
    assert model.calls == [SEMANTIC_TOOL_NAME, REWRITE_TOOL_NAME]


def test_f_orc_002_shadow_validates_without_writing_or_consuming(tmp_path: Path) -> None:
    pipeline, state, _fetcher, _model = _pipeline(tmp_path, shadow=True)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.SHADOW_READY
    assert outcome.output_path is not None
    assert not outcome.output_path.exists()
    assert not (tmp_path / "data").exists()
    assert state.load_seen_ids() == set()


def test_f_orc_003_structured_location_stops_before_external_boundaries(tmp_path: Path) -> None:
    pipeline, state, fetcher, model = _pipeline(tmp_path, shadow=False)
    listing = Listing(
        id="outside-us",
        company_name="Fictional Systems",
        title="Software Engineering Intern",
        url="https://example.invalid/outside-us",
        locations=("Toronto, Ontario, Canada",),
        active=True,
    )

    outcome = pipeline.run([listing]).outcomes[0]

    assert outcome.status is PipelineStatus.DISQUALIFIED
    assert fetcher.calls == []
    assert model.calls == []
    assert state.load_seen_ids() == {listing.id}


def test_f_orc_004_retryable_fetch_is_not_terminal(tmp_path: Path) -> None:
    fetcher = FixtureFetcher(
        {_listing().id: {"status": "retryable_failure", "failure_reason": "fixture timeout"}}
    )
    pipeline, state, _fetcher, model = _pipeline(tmp_path, shadow=False, fetcher=fetcher)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.RETRYABLE_FAILURE
    assert state.load_seen_ids() == set()
    assert state.load_retry_counts() == {_listing().id: 1}
    assert model.calls == []


def test_f_orc_005_false_model_claim_routes_to_manual_review(tmp_path: Path) -> None:
    model = FakeModel(rewrite={"section_order": ["Experience", "Education"], "replacements": []})
    pipeline, state, _fetcher, _model = _pipeline(tmp_path, shadow=False, model=model)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.MANUAL_REVIEW
    assert state.manual_review_count() == 1
    assert not (tmp_path / "data").exists()


def test_f_orc_003_tier_one_disqualification_stops_before_model(tmp_path: Path) -> None:
    fetcher = FixtureFetcher(
        {
            _listing().id: {
                "status": "success",
                "text": "A pre-employment drug test is required for this fictional role.",
            }
        }
    )
    pipeline, _state, _fetcher, model = _pipeline(tmp_path, shadow=False, fetcher=fetcher)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.DISQUALIFIED
    assert model.calls == []


def test_f_orc_004_tier_two_disqualification_stops_before_rewrite(tmp_path: Path) -> None:
    model = FakeModel(
        semantic={
            "drug_testing": {
                "disqualified": False,
                "confidence": "high",
                "evidence": "none stated",
            },
            "security_clearance": {
                "disqualified": True,
                "confidence": "high",
                "evidence": "active clearance required",
            },
            "location_is_us": {
                "confirmed": True,
                "confidence": "high",
                "evidence": "Denver, Colorado",
            },
        }
    )
    pipeline, _state, _fetcher, _model = _pipeline(tmp_path, shadow=False, model=model)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.DISQUALIFIED
    assert model.calls == [SEMANTIC_TOOL_NAME]


def test_f_orc_005_dedupe_stops_before_rewrite_and_assembly(tmp_path: Path) -> None:
    existing = (
        tmp_path / "data" / "2027" / "fictional-systems" / "engineering-software_12-31-26.docx"
    )
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"fictional prior output marker")
    pipeline, state, _fetcher, model = _pipeline(tmp_path, shadow=False)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.DEDUPE_SKIPPED
    assert outcome.output_path == existing
    assert model.calls == [SEMANTIC_TOOL_NAME]
    assert state.load_seen_ids() == {_listing().id}


def test_f_orc_007_assembly_failure_leaves_no_final_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_interner.documents.assembler import DocumentAssemblyError

    def fail_assembly(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise DocumentAssemblyError("fictional injected failure")

    monkeypatch.setattr("auto_interner.application.assemble_resume", fail_assembly)
    pipeline, state, _fetcher, _model = _pipeline(tmp_path, shadow=False)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.RETRYABLE_FAILURE
    assert state.load_seen_ids() == set()
    assert list((tmp_path / "data").rglob("*.docx")) == []


def test_f_orc_008_one_hundred_listing_window_has_one_outcome_each(tmp_path: Path) -> None:
    pipeline, state, fetcher, model = _pipeline(tmp_path, shadow=False)
    listings = [
        Listing(
            id=f"outside-{index}",
            company_name=f"Fictional Company {index}",
            title="Software Intern",
            url=f"https://example.invalid/outside-{index}",
            locations=("Toronto, Ontario, Canada",),
            active=True,
        )
        for index in range(100)
    ]

    result = pipeline.run(listings)

    assert len(result.outcomes) == 100
    assert len({outcome.listing_id for outcome in result.outcomes}) == 100
    assert result.windows_processed == 10
    assert state.load_seen_ids() == {listing.id for listing in listings}
    assert fetcher.calls == []
    assert model.calls == []


def test_f_orc_009_through_011_seen_ids_survive_repeat_addition_and_reorder(
    tmp_path: Path,
) -> None:
    pipeline, state, _fetcher, _model = _pipeline(tmp_path, shadow=False)
    first = Listing(
        id="first",
        company_name="Fictional One",
        title="Software Intern",
        url="https://example.invalid/first",
        locations=("Toronto, Ontario, Canada",),
        active=True,
    )
    second = Listing(
        id="second",
        company_name="Fictional Two",
        title="Software Intern",
        url="https://example.invalid/second",
        locations=("Toronto, Ontario, Canada",),
        active=True,
    )

    initial = pipeline.run([first])
    repeated = pipeline.run([first])
    added = pipeline.run([first, second])
    reordered = pipeline.run([second, first])

    assert len(initial.outcomes) == 1
    assert repeated.outcomes == ()
    assert [outcome.listing_id for outcome in added.outcomes] == [second.id]
    assert reordered.outcomes == ()
    assert state.load_seen_ids() == {first.id, second.id}


def _routing_listing(listing_id: str, location: str, *, active: bool = True) -> Listing:
    return Listing(
        id=listing_id,
        company_name=f"Fictional {listing_id.title()}",
        title="Software Engineering Intern",
        url=f"https://example.invalid/{listing_id}",
        locations=(location,),
        active=active,
    )


def test_mixed_snapshot_routes_every_deterministic_outcome(tmp_path: Path) -> None:
    """One windowed run reaches each terminal and nonterminal status exactly once."""
    listings = [
        _routing_listing("location", "Toronto, Ontario, Canada"),
        _routing_listing("keyword", "Denver, CO"),
        _routing_listing("pass", "Remote in US"),
        _routing_listing("retry", "Austin, TX"),
        _routing_listing("inactive", "Seattle, WA", active=False),
    ]
    fetcher = FixtureFetcher(
        {
            "keyword": {
                "status": "success",
                "text": "An active security clearance is required for this fictional role.",
            },
            "pass": {"status": "success", "text": POSTING},
            "retry": {"status": "retryable_failure", "failure_reason": "fixture timeout"},
        }
    )
    pipeline, state, _fetcher, _model = _pipeline(
        tmp_path, shadow=True, fetcher=fetcher, window_size=2
    )

    result = pipeline.run(listings)

    assert result.as_dict() == {
        "source_records": 5,
        "active_records": 4,
        "skipped_seen": 0,
        "windows_processed": 2,
        "processed": 4,
        "terminal": 2,
        "status_counts": {
            "disqualified": 2,
            "shadow_ready": 1,
            "retryable_failure": 1,
        },
    }
    assert fetcher.calls == ["keyword", "pass", "retry"]
    assert state.load_seen_ids() == {"location", "keyword"}


def test_second_run_reprocesses_only_nonterminal_listings(tmp_path: Path) -> None:
    """A shadow-ready listing stays eligible while terminal ones are skipped."""
    listings = [
        _routing_listing("location", "Toronto, Ontario, Canada"),
        _routing_listing("keyword", "Denver, CO"),
        _routing_listing("pass", "Remote in US"),
    ]
    fetcher = FixtureFetcher(
        {
            "keyword": {
                "status": "success",
                "text": "A security clearance is required for this fictional role.",
            },
            "pass": {"status": "success", "text": POSTING},
        }
    )
    pipeline, _state, _fetcher, _model = _pipeline(tmp_path, shadow=True, fetcher=fetcher)

    first = pipeline.run(listings)
    second = pipeline.run(listings)

    assert [outcome.status for outcome in first.outcomes] == [
        PipelineStatus.DISQUALIFIED,
        PipelineStatus.DISQUALIFIED,
        PipelineStatus.SHADOW_READY,
    ]
    assert [outcome.status for outcome in second.outcomes] == [PipelineStatus.SHADOW_READY]
    assert second.skipped_seen == 2
    assert fetcher.calls == ["keyword", "pass", "pass"]


def test_fetch_exceptions_retry_then_become_manual_review(tmp_path: Path) -> None:
    """A raising adapter is retried, and its private message never reaches state."""

    class RaisingFetcher:
        def fetch(self, listing: Listing, *, attempt_number: int) -> FetchResult:
            del listing, attempt_number
            raise TimeoutError("private boundary detail is not persisted")

    listing = _routing_listing("unstable", "Denver, CO")
    pipeline, state, _fetcher, _model = _pipeline(
        tmp_path,
        shadow=True,
        fetcher=cast(FixtureFetcher, RaisingFetcher()),
        max_attempts=2,
    )

    first = pipeline.run([listing])
    second = pipeline.run([listing])

    assert first.outcomes[0].status is PipelineStatus.RETRYABLE_FAILURE
    assert second.outcomes[0].status is PipelineStatus.MANUAL_REVIEW
    assert state.load_seen_ids() == {listing.id}
    decisions = state.decisions_path.read_text(encoding="utf-8")
    assert "private boundary detail" not in decisions
    assert "adapter raised TimeoutError" in decisions


def test_permanent_fetch_failure_enters_manual_review_with_adapter_reason(
    tmp_path: Path,
) -> None:
    """A permanent fetch failure is terminal and keeps the adapter's sanitized reason."""
    fetcher = FixtureFetcher(
        {"missing": {"status": "permanent_failure", "failure_reason": "fixture missing"}}
    )
    pipeline, state, _fetcher, _model = _pipeline(tmp_path, shadow=True, fetcher=fetcher)

    outcome = pipeline.run([_routing_listing("missing", "Denver, CO")]).outcomes[0]

    assert outcome.status is PipelineStatus.MANUAL_REVIEW
    assert outcome.is_terminal
    assert "fixture missing" in state.manual_review_path.read_text(encoding="utf-8")


def test_malformed_semantic_output_retries_without_body_leakage(tmp_path: Path) -> None:
    """An off-schema Tier 2 payload is retryable and is never persisted."""
    private_marker = "private-model-body-marker"
    model = FakeModel(semantic={"invalid": private_marker})
    pipeline, state, _fetcher, _model = _pipeline(tmp_path, shadow=True, model=model)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.RETRYABLE_FAILURE
    assert private_marker not in state.decisions_path.read_text(encoding="utf-8")


def test_permanent_provider_failure_enters_manual_review(tmp_path: Path) -> None:
    """A nonretryable provider failure is terminal without leaking provider detail."""

    class FailingModel(FakeModel):
        def call_tool(self, **kwargs: object) -> object:
            raise ModelBoundaryError("private provider detail", retryable=False)

    pipeline, state, _fetcher, _model = _pipeline(tmp_path, shadow=True, model=FailingModel())

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.MANUAL_REVIEW
    assert "private provider detail" not in state.decisions_path.read_text(encoding="utf-8")


class _RewriteFailureModel(FakeModel):
    """Pass Tier 2, then fail only at the rewrite boundary."""

    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self.failure = failure

    def call_tool(self, **kwargs: object) -> object:
        if kwargs["tool_name"] == REWRITE_TOOL_NAME:
            raise self.failure
        return super().call_tool(**kwargs)  # type: ignore[arg-type]


def test_retryable_rewrite_failure_is_not_terminal(tmp_path: Path) -> None:
    """An off-schema rewrite response is retried rather than consuming the listing."""
    model = _RewriteFailureModel(RewriteResponseError("private schema detail"))
    pipeline, state, _fetcher, _model = _pipeline(tmp_path, shadow=True, model=model)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.RETRYABLE_FAILURE
    assert state.load_seen_ids() == set()
    decisions = state.decisions_path.read_text(encoding="utf-8")
    assert "private schema detail" not in decisions
    assert "resume rewrite failed temporarily" in decisions


def test_permanent_rewrite_failure_enters_manual_review(tmp_path: Path) -> None:
    """A nonretryable rewrite-boundary failure is terminal and stops before assembly."""
    model = _RewriteFailureModel(ModelBoundaryError("private provider detail", retryable=False))
    pipeline, state, _fetcher, _model = _pipeline(tmp_path, shadow=False, model=model)

    outcome = pipeline.run([_listing()]).outcomes[0]

    assert outcome.status is PipelineStatus.MANUAL_REVIEW
    assert state.manual_review_count() == 1
    assert not (tmp_path / "data").exists()
    assert "private provider detail" not in state.manual_review_path.read_text(encoding="utf-8")
