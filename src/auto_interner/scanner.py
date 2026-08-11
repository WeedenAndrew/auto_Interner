"""Windowed active-listing scanning with order-independent seen checks."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import batched

from auto_interner.models import Listing


def select_unseen_active(listings: Iterable[Listing], seen_ids: set[str]) -> tuple[Listing, ...]:
    """Return every active unseen ID at most once, preserving source order."""
    encountered = set(seen_ids)
    unseen: list[Listing] = []
    for listing in listings:
        if not listing.active or listing.id in encountered:
            continue
        encountered.add(listing.id)
        unseen.append(listing)
    return tuple(unseen)


def iter_unseen_windows(
    listings: Iterable[Listing], seen_ids: set[str], window_size: int
) -> Iterator[tuple[Listing, ...]]:
    """Scan the complete active snapshot while bounding each processing window."""
    encountered = set(seen_ids)
    active_listings = (listing for listing in listings if listing.active)
    for window in batched(active_listings, window_size):
        unseen: list[Listing] = []
        for listing in window:
            if listing.id in encountered:
                continue
            encountered.add(listing.id)
            unseen.append(listing)
        if unseen:
            yield tuple(unseen)
