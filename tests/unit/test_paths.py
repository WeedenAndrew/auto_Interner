"""Phase 3 portable output-path planning and containment cases."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from auto_interner.models import Listing
from auto_interner.paths import (
    OutputCollisionError,
    OutputPathError,
    OutputPathPlanner,
    safe_path_component,
)

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.portability]


def _listing(
    *,
    listing_id: str = "fixture-listing-one",
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


def _timestamp() -> datetime:
    return datetime(2027, 8, 6, 12, 30, tzinfo=UTC)


def test_f_pth_001_normal_company_and_title_produce_expected_relative_path(
    tmp_path: Path,
) -> None:
    planner = OutputPathPlanner(tmp_path / "data", 2027)

    plan = planner.plan(_listing(), generated_at=_timestamp())

    assert plan.output_path.relative_to(tmp_path / "data") == Path(
        "2027/fictional-systems/engineer-software_08-06-27.docx"
    )
    assert not (tmp_path / "data").exists()


def test_f_pth_002_windows_invalid_characters_are_replaced_consistently() -> None:
    component = safe_path_component(
        'Fictional<>:"/\\|?* Systems',
        fallback_prefix="company",
        listing_id="fixture-one",
    )

    assert component == "fictional-systems"


@pytest.mark.parametrize("company", ["../Outside", "C:\\Windows\\System32", "/etc/passwd"])
def test_f_pth_003_and_004_untrusted_path_text_remains_inside_data_dir(
    tmp_path: Path, company: str
) -> None:
    data_dir = tmp_path / "data"
    plan = OutputPathPlanner(data_dir, 2027).plan(
        _listing(company=company), generated_at=_timestamp()
    )

    plan.output_path.resolve(strict=False).relative_to(data_dir.resolve(strict=False))
    assert ".." not in plan.company_component
    assert "/" not in plan.company_component
    assert "\\" not in plan.company_component


def test_f_pth_005_reserved_windows_device_name_gets_safe_prefix(tmp_path: Path) -> None:
    plan = OutputPathPlanner(tmp_path / "data", 2027).plan(
        _listing(company="CON"), generated_at=_timestamp()
    )

    assert plan.company_component == "item-con"


def test_f_pth_006_trailing_dots_and_spaces_are_removed(tmp_path: Path) -> None:
    plan = OutputPathPlanner(tmp_path / "data", 2027).plan(
        _listing(company="Fictional Systems...   "), generated_at=_timestamp()
    )

    assert plan.company_component == "fictional-systems"


def test_f_pth_007_unicode_lookalike_separators_cannot_escape(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    plan = OutputPathPlanner(data_dir, 2027).plan(
        _listing(company="Fictional∕..／Outside＼Division"), generated_at=_timestamp()
    )

    plan.output_path.resolve(strict=False).relative_to(data_dir.resolve(strict=False))
    assert plan.company_component == "fictional-outside-division"


def test_f_pth_008_empty_sanitized_name_uses_stable_listing_fallback(tmp_path: Path) -> None:
    planner = OutputPathPlanner(tmp_path / "data", 2027)

    first = planner.plan(_listing(company="***"), generated_at=_timestamp())
    second = planner.plan(_listing(company="／／／"), generated_at=_timestamp())

    assert first.company_component.startswith("company-")
    assert second.company_component == first.company_component


def test_fallback_prefix_is_sanitized_before_it_becomes_a_component() -> None:
    component = safe_path_component(
        "***",
        fallback_prefix="../Unsafe Prefix",
        listing_id="fixture-one",
    )

    assert component.startswith("unsafe-prefix-")
    assert ".." not in component


def test_f_pth_009_long_roles_are_bounded_and_keep_collision_resistance(tmp_path: Path) -> None:
    planner = OutputPathPlanner(tmp_path / "data", 2027)
    common = " ".join(f"domain{number}" for number in range(100))

    first = planner.plan(_listing(title=f"{common} Alpha"), generated_at=_timestamp())
    second = planner.plan(_listing(title=f"{common} Beta"), generated_at=_timestamp())

    assert len(first.role_component) <= 80
    assert len(first.role_component.encode("utf-8")) <= 180
    assert first.role_component != second.role_component


def test_component_is_also_bounded_by_encoded_byte_length() -> None:
    component = safe_path_component(
        "界" * 70,
        fallback_prefix="role",
        listing_id="fixture-unicode",
    )

    assert len(component) <= 80
    assert len(component.encode("utf-8")) <= 180


def test_f_pth_010_cycle_tree_is_created_only_during_explicit_preparation(
    tmp_path: Path,
) -> None:
    planner = OutputPathPlanner(tmp_path / "data", 2027)
    plan = planner.plan(_listing(), generated_at=_timestamp())

    assert not planner.cycle_dir.exists()
    output_path = planner.prepare(plan)

    assert plan.company_dir.is_dir()
    assert output_path == plan.output_path
    assert not output_path.exists()


def test_f_pth_011_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    planner = OutputPathPlanner(tmp_path / "data", 2027)
    plan = planner.plan(_listing(), generated_at=_timestamp())
    output_path = planner.prepare(plan)
    output_path.write_bytes(b"fictional existing document")

    with pytest.raises(OutputCollisionError, match="refusing to overwrite"):
        planner.prepare(plan)

    assert output_path.read_bytes() == b"fictional existing document"


def test_forged_output_plan_is_rejected_before_directories_are_created(tmp_path: Path) -> None:
    planner = OutputPathPlanner(tmp_path / "data", 2027)
    plan = planner.plan(_listing(), generated_at=_timestamp())
    forged = replace(plan, output_path=tmp_path / "outside.docx")

    with pytest.raises(OutputPathError, match="does not belong"):
        planner.prepare(forged)

    assert not planner.cycle_dir.exists()


def test_generation_timestamp_requires_an_explicit_timezone(tmp_path: Path) -> None:
    planner = OutputPathPlanner(tmp_path / "data", 2027)

    with pytest.raises(ValueError, match="timezone"):
        planner.plan(_listing(), generated_at=datetime(2027, 8, 6, 12, 30))


def test_invalid_recruiting_year_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 2000 and 2100"):
        OutputPathPlanner(Path("data"), 1999)


def test_containment_guard_rejects_a_path_outside_data_dir(tmp_path: Path) -> None:
    planner = OutputPathPlanner(tmp_path / "data", 2027)

    with pytest.raises(OutputPathError, match="inside DATA_DIR"):
        planner._assert_contained(tmp_path / "outside.docx")


def test_symbolic_company_directory_is_rejected_before_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planner = OutputPathPlanner(tmp_path / "data", 2027)
    plan = planner.plan(_listing(), generated_at=_timestamp())
    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        return path == plan.company_dir or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    with pytest.raises(OutputPathError, match="symbolic link"):
        planner.prepare(plan)

    assert not planner.cycle_dir.exists()
