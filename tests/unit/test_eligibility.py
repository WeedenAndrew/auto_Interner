"""Tier 0 structured eligibility tests.

The unknown-value cases carry the weight here. This screen is the only place a
listing can be discarded before anything reads the real posting, so an
over-eager rule is invisible everywhere else in the suite.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from auto_interner.models import (
    Listing,
    ScreeningCategory,
    ScreeningDecision,
    ScreeningOutcome,
)
from auto_interner.screening.eligibility import screen_listing_eligibility

pytestmark = [pytest.mark.unit]

NOW = datetime(2026, 8, 19, 12, tzinfo=UTC)


def _listing(
    *,
    terms: tuple[str, ...] = ("Summer 2027",),
    degrees: tuple[str, ...] = ("Bachelor's",),
    category: str | None = "Software",
) -> Listing:
    return Listing(
        id="listing-1",
        company_name="Pine Labs",
        title="Software Engineering Intern",
        url="https://example.invalid/jobs/1",
        locations=("Austin, TX",),
        active=True,
        terms=terms,
        degrees=degrees,
        category=category,
    )


def _screen(listing: Listing, *, year: int = 2027) -> ScreeningDecision | None:
    return screen_listing_eligibility(listing, recruiting_year=year, decided_at=NOW)


def _categories(listing: Listing) -> set[ScreeningCategory]:
    decision = _screen(listing)
    assert decision is not None
    assert decision.outcome is ScreeningOutcome.DISQUALIFY
    return {item.category for item in decision.evidence}


def test_a_matching_listing_passes() -> None:
    assert _screen(_listing()) is None


def test_the_wrong_season_is_disqualified() -> None:
    assert _categories(_listing(terms=("Summer 2026",))) == {ScreeningCategory.RECRUITING_TERM}


def test_a_graduate_only_posting_is_disqualified() -> None:
    assert _categories(_listing(degrees=("Master's", "PhD"))) == {ScreeningCategory.DEGREE_LEVEL}


def test_another_discipline_is_disqualified() -> None:
    assert _categories(_listing(category="Hardware")) == {ScreeningCategory.ROLE_CATEGORY}


@pytest.mark.parametrize(
    "listing",
    [
        _listing(terms=()),
        _listing(terms=("N/A",)),
        _listing(terms=("",)),
        _listing(degrees=()),
        _listing(category=None),
        _listing(category=""),
    ],
    ids=["no-terms", "terms-na", "terms-blank", "no-degrees", "no-category", "blank-category"],
)
def test_an_unknown_value_never_disqualifies(listing: Listing) -> None:
    """A false disqualification here is permanent, silent, and never revisited."""
    assert _screen(listing) is None


def test_one_wanted_term_among_several_passes() -> None:
    assert _screen(_listing(terms=("Summer 2026", "Summer 2027"))) is None


def test_a_bachelors_option_passes_beside_graduate_degrees() -> None:
    assert _screen(_listing(degrees=("Bachelor's", "Master's", "PhD"))) is None


def test_every_failing_rule_is_recorded_not_just_the_first() -> None:
    """The decision log should explain the whole reason, not whichever ran first."""
    assert _categories(_listing(terms=("Fall 2026",), degrees=("PhD",), category="Hardware")) == {
        ScreeningCategory.RECRUITING_TERM,
        ScreeningCategory.DEGREE_LEVEL,
        ScreeningCategory.ROLE_CATEGORY,
    }


def test_the_wanted_season_follows_the_configured_year() -> None:
    """A 2028 cycle must not inherit 2027's listings, or vice versa."""
    listing = _listing(terms=("Summer 2028",))
    assert _screen(listing, year=2028) is None
    assert _screen(listing, year=2027) is not None
