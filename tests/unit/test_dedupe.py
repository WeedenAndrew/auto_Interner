"""Phase 3 company, role, date-boundary, and cycle-isolation cases."""

from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import permutations
from pathlib import Path

import pytest

from auto_interner.dedupe import RoleDeduplicator, six_calendar_month_cutoff
from auto_interner.models import Listing
from auto_interner.paths import OutputPathPlanner, normalize_role

pytestmark = pytest.mark.unit

_AS_OF = datetime(2027, 8, 31, 12, tzinfo=UTC)


def _listing(
    *,
    listing_id: str = "fixture-current",
    company: str = "Fictional Systems",
    title: str = "Software Engineer Intern",
) -> Listing:
    return Listing(
        id=listing_id,
        company_name=company,
        title=title,
        url="https://example.invalid/jobs/fixture",
        locations=("Denver, CO",),
        active=True,
    )


def _generated_resume(
    data_dir: Path,
    *,
    year: int = 2027,
    company: str = "Fictional Systems",
    title: str = "Software Engineer Intern",
    generated_at: datetime,
) -> Path:
    listing = _listing(listing_id=f"fixture-{generated_at:%Y%m%d}", company=company, title=title)
    planner = OutputPathPlanner(data_dir, year)
    plan = planner.plan(listing, generated_at=generated_at)
    path = planner.prepare(plan)
    path.write_bytes(b"fictional generated document placeholder")
    return path


def test_f_ded_001_same_company_and_role_within_six_months_is_duplicate(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    existing = _generated_resume(data_dir, generated_at=datetime(2027, 6, 15, 9, tzinfo=UTC))

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is True
    assert result.matched_path == existing
    assert result.matched_generated_on == date(2027, 6, 15)


def test_f_ded_002_same_role_older_than_six_months_proceeds(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _generated_resume(data_dir, generated_at=datetime(2027, 1, 31, 9, tzinfo=UTC))

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False


def test_f_ded_003_same_company_different_domain_role_proceeds(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _generated_resume(
        data_dir,
        title="Data Engineer Intern",
        generated_at=datetime(2027, 7, 1, 9, tzinfo=UTC),
    )

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False


def test_f_ded_004_different_company_same_role_proceeds(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _generated_resume(
        data_dir,
        company="Another Fictional Company",
        generated_at=datetime(2027, 7, 1, 9, tzinfo=UTC),
    )

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False


def test_f_ded_005_noise_tokens_do_not_change_role_identity(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _generated_resume(
        data_dir,
        title="Summer 2027 Software Engineer Co-op",
        generated_at=datetime(2027, 7, 1, 9, tzinfo=UTC),
    )
    current = _listing(title="Software Engineer Internship")

    result = RoleDeduplicator(data_dir, 2027).check(current, as_of=_AS_OF)

    assert result.is_duplicate is True


def test_f_ded_006_token_order_does_not_change_role_identity(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _generated_resume(
        data_dir,
        title="Backend Software Engineer Intern",
        generated_at=datetime(2027, 7, 1, 9, tzinfo=UTC),
    )
    current = _listing(title="Engineer Backend Software")

    assert RoleDeduplicator(data_dir, 2027).check(current, as_of=_AS_OF).is_duplicate


def test_f_ded_007_punctuation_and_case_do_not_change_role_identity(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _generated_resume(
        data_dir,
        title="SOFTWARE, ENGINEER! INTERN",
        generated_at=datetime(2027, 7, 1, 9, tzinfo=UTC),
    )

    assert RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF).is_duplicate


def test_f_ded_008_engineer_and_engineering_remain_distinct_in_v1(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _generated_resume(
        data_dir,
        title="Software Engineering Intern",
        generated_at=datetime(2027, 7, 1, 9, tzinfo=UTC),
    )

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False


def test_f_ded_009_previous_recruiting_cycle_is_not_consulted(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _generated_resume(
        data_dir,
        year=2026,
        generated_at=datetime(2027, 7, 1, 9, tzinfo=UTC),
    )

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False
    assert not (data_dir / "2027").exists()


def test_f_ded_010_exactly_six_calendar_months_old_proceeds(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _generated_resume(data_dir, generated_at=datetime(2027, 2, 28, 9, tzinfo=UTC))

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.cutoff_date == date(2027, 2, 28)
    assert result.is_duplicate is False


def test_f_ded_011_malformed_filename_is_ignored_and_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    data_dir = tmp_path / "data"
    planner = OutputPathPlanner(data_dir, 2027)
    company_dir = planner.cycle_dir / planner.company_component(_listing())
    company_dir.mkdir(parents=True)
    (company_dir / "malformed.docx").write_bytes(b"fictional malformed placeholder")

    with caplog.at_level("WARNING", logger="auto_interner.dedupe"):
        result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False
    assert result.anomalies[0].code == "malformed_filename"
    assert "Ignored generated-resume entry" in caplog.text


def test_f_ded_012_random_token_order_is_normalization_invariant() -> None:
    tokens = ("software", "machine", "learning", "engineer")
    expected = normalize_role(" ".join(tokens))

    assert all(normalize_role(" ".join(order)) == expected for order in permutations(tokens))


def test_long_role_component_still_matches_its_generated_filename(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    title = " ".join(f"domain{number}" for number in range(100))
    _generated_resume(
        data_dir,
        title=title,
        generated_at=datetime(2027, 7, 1, 9, tzinfo=UTC),
    )

    result = RoleDeduplicator(data_dir, 2027).check(
        _listing(title=title),
        as_of=_AS_OF,
    )

    assert result.is_duplicate is True


def test_future_generated_date_is_an_anomaly_and_never_a_duplicate(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _generated_resume(data_dir, generated_at=datetime(2027, 9, 1, 9, tzinfo=UTC))

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False
    assert result.anomalies[0].code == "future_date"


@pytest.mark.parametrize(
    ("filename", "expected_code"),
    [
        ("intern_07-01-27.docx", "missing_role"),
        ("engineer-software_02-30-27.docx", "invalid_date"),
    ],
)
def test_unusable_generated_filename_details_are_anomalies(
    tmp_path: Path, filename: str, expected_code: str
) -> None:
    data_dir = tmp_path / "data"
    planner = OutputPathPlanner(data_dir, 2027)
    company_dir = planner.cycle_dir / planner.company_component(_listing())
    company_dir.mkdir(parents=True)
    (company_dir / filename).write_bytes(b"fictional malformed placeholder")

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False
    assert result.anomalies[0].code == expected_code


def test_docx_directory_entry_is_ignored_as_unsafe(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    planner = OutputPathPlanner(data_dir, 2027)
    company_dir = planner.cycle_dir / planner.company_component(_listing())
    company_dir.mkdir(parents=True)
    (company_dir / "engineer-software_07-01-27.docx").mkdir()

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False
    assert result.anomalies[0].code == "unsafe_entry"


def test_non_docx_entries_are_ignored_without_anomaly(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    planner = OutputPathPlanner(data_dir, 2027)
    company_dir = planner.cycle_dir / planner.company_component(_listing())
    company_dir.mkdir(parents=True)
    (company_dir / "notes.txt").write_text("fictional note", encoding="utf-8")

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False
    assert result.anomalies == ()


def test_company_output_path_that_is_not_a_directory_fails_closed(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    planner = OutputPathPlanner(data_dir, 2027)
    company_path = planner.cycle_dir / planner.company_component(_listing())
    company_path.parent.mkdir(parents=True)
    company_path.write_text("not a directory", encoding="utf-8")

    result = RoleDeduplicator(data_dir, 2027).check(_listing(), as_of=_AS_OF)

    assert result.is_duplicate is False
    assert result.anomalies[0].code == "unsafe_company_directory"


def test_role_with_only_noise_tokens_proceeds_conservatively_without_filesystem_writes(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"

    result = RoleDeduplicator(data_dir, 2027).check(
        _listing(title="Summer 2027 Internship"), as_of=_AS_OF
    )

    assert result.is_duplicate is False
    assert result.normalized_role == ""
    assert not data_dir.exists()


def test_dedupe_timestamp_requires_an_explicit_timezone(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone"):
        RoleDeduplicator(tmp_path / "data", 2027).check(_listing(), as_of=datetime(2027, 8, 31, 12))


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (date(2027, 8, 31), date(2027, 2, 28)),
        (date(2028, 8, 31), date(2028, 2, 29)),
        (date(2027, 3, 31), date(2026, 9, 30)),
    ],
)
def test_six_month_cutoff_clamps_end_of_month(as_of: date, expected: date) -> None:
    assert six_calendar_month_cutoff(as_of) == expected
