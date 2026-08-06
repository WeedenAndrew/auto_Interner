"""F-L0 conservative structured-location cases."""

from __future__ import annotations

import pytest

from auto_interner.screening.location import (
    LocationClassification,
    LocationScreenStatus,
    classify_location,
    screen_locations,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "location",
    ["Colorado", "New York", "District of Columbia", "Denver, CO", "Portland, OR"],
)
def test_f_l0_001_and_002_state_names_and_abbreviations_pass(location: str) -> None:
    assert classify_location(location) is LocationClassification.US


@pytest.mark.parametrize(
    "location",
    ["United States", "USA", "Remote in USA", "Remote in US", "NYC", "LA", "SF"],
)
def test_f_l0_003_and_004_explicit_us_forms_pass(location: str) -> None:
    assert classify_location(location) is LocationClassification.US


def test_f_l0_005_any_us_option_makes_combined_result_pass() -> None:
    result = screen_locations(("Toronto, Canada", "Seattle, WA"))

    assert result.status is LocationScreenStatus.PASS


def test_f_l0_006_all_recognized_non_us_locations_disqualify() -> None:
    result = screen_locations(("Toronto, Canada", "Berlin, Germany"))

    assert result.status is LocationScreenStatus.DISQUALIFY


@pytest.mark.parametrize("locations", [("Distributed",), (), ("Toronto, Canada", "Distributed")])
def test_f_l0_007_and_008_unknown_values_never_disqualify(locations: tuple[str, ...]) -> None:
    assert screen_locations(locations).status is LocationScreenStatus.UNKNOWN


@pytest.mark.parametrize("location", ["business", "trustworthy", "Lausanne", "SFO"])
def test_f_l0_009_unrelated_substrings_do_not_match(location: str) -> None:
    assert classify_location(location) is LocationClassification.UNKNOWN


def test_f_l0_010_case_whitespace_and_unicode_are_normalized() -> None:
    assert classify_location("  remote   IN   usa  ") is LocationClassification.US
    assert classify_location("Ａｕｓｔｉｎ， ＴＸ") is LocationClassification.US


def test_remote_us_inside_composite_location_prevents_non_us_classification() -> None:
    location = "London, UK / Remote in U.S."

    assert classify_location(location) is LocationClassification.US
