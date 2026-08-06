"""F-ORC complete application-pipeline integration cases."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import pytest

from auto_interner.application import ApplicationPipeline
from auto_interner.dedupe import RoleDeduplicator
from auto_interner.demo import FixtureFetcher
from auto_interner.models import Listing, PipelineStatus
from auto_interner.paths import OutputPathPlanner
from auto_interner.rewriting.service import REWRITE_TOOL_NAME
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
            window_size=10,
            max_attempts=3,
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
