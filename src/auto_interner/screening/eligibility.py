"""Tier 0 structured eligibility, decided before anything is fetched or paid for.

Every other screening tier costs something. Tier 1 needs the posting body, so it
costs a fetch; Tier 2 costs a model call on top. This module reads three fields
the snapshot already carries -- recruiting term, accepted degrees, and role
category -- and answers "is this even the kind of job being looked for?" for
free, before either.

Measured against the live Summer 2027 snapshot on 2026-08-19, the three rules
together took 1,670 active listings to 339. The season rule alone accounted for
1,100 of that: the repository is named for one cycle but carries every cycle,
and nothing had been reading `terms`.

**Unknown always passes.** A missing, empty or unrecognised value leaves the
listing eligible and lets the later tiers decide on the real posting text. That
is the same bias the location screen takes, and for the same reason: the cost of
a wasted model call is a few cents, and the cost of a false disqualification is
an internship that silently never gets applied to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from auto_interner.models import (
    Confidence,
    EvidenceDecision,
    Listing,
    ScreeningCategory,
    ScreeningDecision,
    ScreeningEvidence,
    ScreeningOutcome,
    ScreeningTier,
)

# Upstream writes terms as "<Season> <Year>". Only the configured cycle is
# wanted, but "N/A" is upstream's own placeholder for "not stated" and has to
# read as unknown rather than as a mismatch.
_UNKNOWN_TERMS = frozenset({"n/a", "na", "unknown", ""})

# A Bachelor's candidate. A posting naming only graduate degrees is not
# available to one, but a posting naming none at all says nothing either way.
_ACCEPTED_DEGREE_MARKERS = ("bachelor", "undergrad", "associate")

# Upstream's own taxonomy. Anything outside it is a different discipline rather
# than a harder version of the same one.
_TARGET_CATEGORIES = frozenset(
    {
        "software",
        "software engineering",
        "ai/ml/data",
        "data science, ai & machine learning",
    }
)


# University-employed research and departmental assistant work. On the live
# snapshot this is 54 of 339 otherwise-eligible listings, and reads as
# "Undergraduate Cartographer", "Maps and Geospatial Assistant" and "Physics
# Department - Research Support" -- campus jobs that upstream files under
# software categories.
#
# This is the least conservative rule here and the only one that can plausibly
# discard real work: a university IT department or a research lab does post
# genuine software internships. It is a deliberate personal-scope choice rather
# than a safety property, and the disqualification is recorded with the employer
# name so the decision log shows exactly what it cost.
_UNIVERSITY_EMPLOYER = re.compile(
    r"(universit|college|polytechnic|institute of technology|school of)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class EligibilityRule:
    """One structured reason a listing is not worth spending a fetch on."""

    category: ScreeningCategory
    evidence: str


def _season_label(recruiting_year: int) -> str:
    return f"summer {recruiting_year}"


def _term_rule(listing: Listing, recruiting_year: int) -> EligibilityRule | None:
    stated = [term.strip().casefold() for term in listing.terms if term.strip()]
    known = [term for term in stated if term not in _UNKNOWN_TERMS]
    if not known:
        return None
    if _season_label(recruiting_year) in known:
        return None
    return EligibilityRule(
        category=ScreeningCategory.RECRUITING_TERM,
        evidence=f"every stated term is outside Summer {recruiting_year}",
    )


def _degree_rule(listing: Listing) -> EligibilityRule | None:
    stated = [degree.strip().casefold() for degree in listing.degrees if degree.strip()]
    if not stated:
        return None
    if any(marker in degree for degree in stated for marker in _ACCEPTED_DEGREE_MARKERS):
        return None
    return EligibilityRule(
        category=ScreeningCategory.DEGREE_LEVEL,
        evidence="every accepted degree is a graduate degree",
    )


def _category_rule(listing: Listing) -> EligibilityRule | None:
    stated = (listing.category or "").strip().casefold()
    if not stated or stated in _TARGET_CATEGORIES:
        return None
    return EligibilityRule(
        category=ScreeningCategory.ROLE_CATEGORY,
        evidence="the stated role category is outside the disciplines being searched",
    )


def _employer_rule(listing: Listing) -> EligibilityRule | None:
    company = listing.company_name.strip()
    if not company or not _UNIVERSITY_EMPLOYER.search(company):
        return None
    return EligibilityRule(
        category=ScreeningCategory.EMPLOYER_TYPE,
        evidence=f"university employer, out of personal scope: {company}",
    )


def screen_listing_eligibility(
    listing: Listing,
    *,
    recruiting_year: int,
    decided_at: datetime,
) -> ScreeningDecision | None:
    """Return a disqualification, or None when the listing stays eligible.

    Every rule that fires is recorded, not just the first, so a decision log
    entry explains the whole reason rather than whichever check ran earliest.
    """
    rules = (
        _term_rule(listing, recruiting_year),
        _degree_rule(listing),
        _category_rule(listing),
        _employer_rule(listing),
    )
    fired = [rule for rule in rules if rule is not None]
    if not fired:
        return None
    return ScreeningDecision(
        listing_id=listing.id,
        outcome=ScreeningOutcome.DISQUALIFY,
        evidence=tuple(
            ScreeningEvidence(
                category=rule.category,
                decision=EvidenceDecision.DISQUALIFY,
                confidence=Confidence.HIGH,
                tier=ScreeningTier.STRUCTURED_ELIGIBILITY,
                evidence=rule.evidence,
            )
            for rule in fired
        ),
        decided_at=decided_at,
    )
