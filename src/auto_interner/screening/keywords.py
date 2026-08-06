"""Data-driven Tier 1 hard-disqualifier patterns."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from auto_interner.models import (
    Confidence,
    EvidenceDecision,
    ScreeningCategory,
    ScreeningDecision,
    ScreeningEvidence,
    ScreeningOutcome,
    ScreeningTier,
)


@dataclass(frozen=True, slots=True)
class KeywordRule:
    """One independently testable Tier 1 pattern."""

    name: str
    category: ScreeningCategory
    pattern: re.Pattern[str]
    evidence: str


def _rule(name: str, category: ScreeningCategory, pattern: str, evidence: str) -> KeywordRule:
    return KeywordRule(name, category, re.compile(pattern, re.IGNORECASE), evidence)


KEYWORD_RULES: Final[tuple[KeywordRule, ...]] = (
    _rule(
        "drug_test",
        ScreeningCategory.DRUG_TESTING,
        r"\bdrug[\s-]+test(?:ing|s)?\b",
        "posting states a drug-testing requirement",
    ),
    _rule(
        "drug_screen",
        ScreeningCategory.DRUG_TESTING,
        r"\bdrug[\s-]+screen(?:ing|s)?\b",
        "posting states a drug-screening requirement",
    ),
    _rule(
        "pre_employment_drug",
        ScreeningCategory.DRUG_TESTING,
        r"\bpre[\s-]+employment\s+drug\b",
        "posting links drug requirements to pre-employment screening",
    ),
    _rule(
        "controlled_substance",
        ScreeningCategory.DRUG_TESTING,
        r"\bcontrolled\s+substances?\b",
        "posting includes a controlled-substance condition",
    ),
    _rule(
        "marijuana",
        ScreeningCategory.DRUG_TESTING,
        r"\bmarijuana\b",
        "posting includes a marijuana condition",
    ),
    _rule(
        "cannabis",
        ScreeningCategory.DRUG_TESTING,
        r"\bcannabis\b",
        "posting includes a cannabis condition",
    ),
    _rule(
        "thc",
        ScreeningCategory.DRUG_TESTING,
        r"\bTHC\b",
        "posting includes a THC condition",
    ),
    _rule(
        "drug_free_workplace",
        ScreeningCategory.DRUG_TESTING,
        r"\bdrug[\s-]+free\s+workplace\b",
        "posting states a drug-free workplace condition",
    ),
    _rule(
        "substance_abuse_screen",
        ScreeningCategory.DRUG_TESTING,
        r"\bsubstance\s+abuse\s+(?:test(?:ing)?|screen(?:ing)?)\b",
        "posting requires substance-abuse screening",
    ),
    _rule(
        "dot_regulated",
        ScreeningCategory.DRUG_TESTING,
        r"\bDOT[\s-]+regulated\b",
        "posting identifies the role as DOT-regulated",
    ),
    _rule(
        "drug_and_alcohol_test",
        ScreeningCategory.DRUG_TESTING,
        r"\bdrug\s+and\s+alcohol\s+(?:test(?:ing)?|screen(?:ing)?)\b",
        "posting requires drug and alcohol screening",
    ),
    _rule(
        "security_clearance",
        ScreeningCategory.SECURITY_CLEARANCE,
        r"\bsecurity\s+clearance\b",
        "posting requires a security clearance",
    ),
    _rule(
        "secret_clearance",
        ScreeningCategory.SECURITY_CLEARANCE,
        r"\bsecret\s+clearance\b",
        "posting requires a secret clearance",
    ),
    _rule(
        "top_secret",
        ScreeningCategory.SECURITY_CLEARANCE,
        r"\btop\s+secret\b",
        "posting requires top-secret eligibility or access",
    ),
    _rule(
        "ts_sci",
        ScreeningCategory.SECURITY_CLEARANCE,
        r"\bTS\s*/\s*SCI\b",
        "posting requires TS/SCI eligibility or access",
    ),
    _rule(
        "public_trust_clearance",
        ScreeningCategory.SECURITY_CLEARANCE,
        r"\bpublic\s+trust\s+clearance\b",
        "posting requires a public-trust clearance",
    ),
    _rule(
        "active_clearance",
        ScreeningCategory.SECURITY_CLEARANCE,
        r"\bactive\s+(?:(?:secret|top\s+secret|security)\s+)?clearance\b",
        "posting requires an active clearance",
    ),
    _rule(
        "obtain_clearance",
        ScreeningCategory.SECURITY_CLEARANCE,
        r"\b(?:must\s+be\s+able\s+to\s+)?(?:obtain|maintain)(?:\s+and\s+maintain)?\s+"
        r"(?:an?\s+)?(?:(?:security|secret)\s+)?clearance\b",
        "posting requires the candidate to obtain or maintain a clearance",
    ),
    _rule(
        "clearance_eligibility",
        ScreeningCategory.SECURITY_CLEARANCE,
        r"\bclearance\s+eligib(?:le|ility)\b",
        "posting requires clearance eligibility",
    ),
)


def normalize_posting_text(text: str) -> str:
    """Normalize Unicode, dash variants, and whitespace before matching."""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("–", "-").replace("—", "-")
    return " ".join(normalized.split())


def screen_posting_text(
    listing_id: str, text: str, *, decided_at: datetime
) -> ScreeningDecision | None:
    """Return a hard disqualification or None when Tier 1 has no match."""
    normalized = normalize_posting_text(text)
    evidence: list[ScreeningEvidence] = []
    matched_categories: set[ScreeningCategory] = set()

    for rule in KEYWORD_RULES:
        if rule.category in matched_categories or not rule.pattern.search(normalized):
            continue
        matched_categories.add(rule.category)
        evidence.append(
            ScreeningEvidence(
                category=rule.category,
                decision=EvidenceDecision.DISQUALIFY,
                confidence=Confidence.HIGH,
                tier=ScreeningTier.DETERMINISTIC_TEXT,
                evidence=rule.evidence,
            )
        )

    if not evidence:
        return None
    return ScreeningDecision(
        listing_id=listing_id,
        outcome=ScreeningOutcome.DISQUALIFY,
        evidence=tuple(evidence),
        decided_at=decided_at,
    )
