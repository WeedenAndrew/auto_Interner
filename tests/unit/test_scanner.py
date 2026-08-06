"""F-SCN windowing and unseen-ID selection cases."""

from __future__ import annotations

import random

import pytest

from auto_interner.models import Listing
from auto_interner.scanner import batched, iter_unseen_windows, select_unseen_active

pytestmark = pytest.mark.unit


def _listing(listing_id: str, *, active: bool = True) -> Listing:
    return Listing(
        id=listing_id,
        company_name="Fictional Systems",
        title="Software Intern",
        url=f"https://example.invalid/{listing_id}",
        locations=("Denver, CO",),
        active=active,
    )


def _window_ids(listings: list[Listing], seen_ids: set[str], size: int) -> list[list[str]]:
    return [
        [listing.id for listing in window]
        for window in iter_unseen_windows(listings, seen_ids, size)
    ]


def test_batched_rejects_nonpositive_size() -> None:
    with pytest.raises(ValueError, match="positive"):
        list(batched([1], 0))


@pytest.mark.parametrize(
    ("seen", "expected"),
    [
        (set(), ("a", "b")),
        ({"a", "b"}, ()),
        ({"a"}, ("b",)),
    ],
)
def test_f_scn_001_to_003_unseen_selection(seen: set[str], expected: tuple[str, ...]) -> None:
    listings = [_listing("a"), _listing("inactive", active=False), _listing("b")]

    assert tuple(item.id for item in select_unseen_active(listings, seen)) == expected


@pytest.mark.parametrize(
    ("count", "size", "lengths"),
    [(2, 5, [2]), (3, 3, [3]), (7, 3, [3, 3, 1])],
)
def test_f_scn_004_to_007_window_sizes(count: int, size: int, lengths: list[int]) -> None:
    listings = [_listing(str(index)) for index in range(count)]

    assert [len(window) for window in iter_unseen_windows(listings, set(), size)] == lengths


def test_f_scn_008_duplicate_crossing_boundary_is_processed_once() -> None:
    listings = [_listing("a"), _listing("b"), _listing("a"), _listing("c")]

    assert _window_ids(listings, set(), 2) == [["a", "b"], ["c"]]


def test_f_src_010_and_f_scn_011_reordering_preserves_unseen_set() -> None:
    listings = [_listing(str(index)) for index in range(20)]
    shuffled = list(listings)
    random.Random(2027).shuffle(shuffled)
    seen = {"2", "7", "13"}

    first = {item.id for item in select_unseen_active(listings, seen)}
    second = {item.id for item in select_unseen_active(shuffled, seen)}
    assert first == second == {str(index) for index in range(20)} - seen
