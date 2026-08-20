"""Reuse of Tier 2 verdicts, keyed by posting content rather than by listing.

Tier 2 is the only paid stage. Three things make the same posting text arrive at
it repeatedly: a shadow run leaves every outcome nonterminal, so an unchanged
snapshot is re-screened on the next cycle; a retry anywhere later in the pipeline
sends a listing back through from the top; and upstream genuinely publishes the
same posting twice under separate IDs. Over a six-month unattended run at a
two-hour cadence, that is the dominant cost.

The cache is keyed on the SHA-256 of the fetched posting text, so it is a
statement about *a posting*, not about a listing. Two listings sharing one
posting body share one verdict, which is correct: Tier 2 only ever reads the
posting.

**Verdicts expire.** A cached entry older than `MAX_AGE` is re-screened rather
than reused, so a model whose behaviour has moved is noticed within a week
instead of being trusted for the whole season.

**A disagreement never disqualifies.** If the re-screen contradicts the stored
verdict, the run proceeds on the non-disqualifying one and the disagreement is
recorded. Acting on the new verdict would let a single drifted call end a
listing permanently, and a disqualification is terminal: there is no later stage
that can undo it. Deferring costs one cycle; being wrong costs the internship.
The cache is refreshed either way, so the next run starts from the new verdict
rather than re-litigating the same disagreement forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Re-screen anything older than this. A week is the operator's stated floor for
# drift checking on a six-month run.
MAX_AGE = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class CachedVerdict:
    """One remembered Tier 2 outcome for a posting body.

    `category` is the serialized ScreeningCategory that fired, kept so a reused
    disqualification records the reason it actually had rather than a placeholder
    one. It is empty when the verdict was a pass.
    """

    disqualified: bool
    screened_at: datetime
    summary: str
    category: str = ""

    def is_fresh(self, *, now: datetime) -> bool:
        """Whether this verdict may still be reused without re-screening."""
        return now - self.screened_at < MAX_AGE


@dataclass(frozen=True, slots=True)
class CacheDecision:
    """What the pipeline should do, and what is worth recording about it."""

    screen_again: bool
    reuse: CachedVerdict | None
    reason: str


def plan_lookup(cached: CachedVerdict | None, *, now: datetime) -> CacheDecision:
    """Decide whether a stored verdict can stand in for a Tier 2 call."""
    if cached is None:
        return CacheDecision(screen_again=True, reuse=None, reason="no cached verdict")
    if not cached.is_fresh(now=now):
        age_days = (now - cached.screened_at).days
        return CacheDecision(
            screen_again=True,
            reuse=cached,
            reason=f"cached verdict is {age_days} days old, past the {MAX_AGE.days}-day limit",
        )
    return CacheDecision(screen_again=False, reuse=cached, reason="reused a fresh cached verdict")


def resolve_disagreement(
    cached: CachedVerdict | None,
    *,
    fresh_disqualified: bool,
) -> tuple[bool, str | None]:
    """Return the verdict to act on, and a drift note when the two differ.

    Returns the non-disqualifying verdict whenever the two disagree, in either
    direction. A stored disqualification the model no longer agrees with is just
    as wrong as a new one it has only now invented, and both resolve the same
    way: pass the listing forward and let a later run settle it.
    """
    if cached is None or cached.disqualified == fresh_disqualified:
        return fresh_disqualified, None
    note = (
        f"tier 2 drift: cached verdict disqualified={cached.disqualified} "
        f"from {cached.screened_at.isoformat()}, re-screen returned "
        f"disqualified={fresh_disqualified}; proceeding without disqualifying"
    )
    return False, note
