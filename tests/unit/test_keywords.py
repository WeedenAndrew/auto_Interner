"""F-L1 deterministic posting-text screening cases."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from auto_interner.models import ScreeningCategory, ScreeningOutcome
from auto_interner.screening.keywords import KEYWORD_RULES, KeywordRule, screen_posting_text

pytestmark = pytest.mark.unit

NOW = datetime(2027, 1, 2, 3, 4, tzinfo=UTC)

POSITIVE_EXAMPLES = {
    "drug_test": "This offer requires a drug test.",
    "drug_screen": "Candidates complete drug screening.",
    "pre_employment_drug": "A pre-employment drug policy applies.",
    "controlled_substance": "The controlled substance policy applies.",
    "marijuana": "The marijuana policy is a condition of employment.",
    "cannabis": "The cannabis policy is a condition of employment.",
    "thc": "The THC policy is a condition of employment.",
    "drug_free_workplace": "This is a drug-free workplace.",
    "substance_abuse_screen": "A substance abuse screening is required.",
    "dot_regulated": "This is a DOT-regulated role.",
    "drug_and_alcohol_test": "A drug and alcohol test is required.",
    "security_clearance": "A security clearance is required.",
    "secret_clearance": "Candidates need a secret clearance.",
    "top_secret": "Candidates need top secret access.",
    "ts_sci": "Candidates need TS/SCI access.",
    "public_trust_clearance": "A public trust clearance is required.",
    "active_clearance": "An active clearance is required.",
    "obtain_clearance": "Candidates must be able to obtain and maintain a clearance.",
    "clearance_eligibility": "Clearance eligibility is required.",
}

NEGATIVE_EXAMPLES = {
    "drug_test": "The testing framework covers distributed systems.",
    "drug_screen": "The screen displays deployment health.",
    "pre_employment_drug": "Pre-employment paperwork is completed online.",
    "controlled_substance": "The controller manages request state.",
    "marijuana": "Work is based in Marijuanaville.",
    "cannabis": "The Cannabister module is internal.",
    "thc": "TheCharlotte office is growing.",
    "drug_free_workplace": "The workplace offers free lunch.",
    "substance_abuse_screen": "The substance of the role is abuse prevention research.",
    "dot_regulated": "Dot products are regulated by numerical tolerances.",
    "drug_and_alcohol_test": "The policy documentation is maintained separately.",
    "security_clearance": "The security team reviews access; code clearance is automated.",
    "secret_clearance": "The secret is stored outside the source tree.",
    "top_secret": "Top performers keep customer data confidential.",
    "ts_sci": "The science team writes TypeScript.",
    "public_trust_clearance": "Public trust matters and account access is reviewed.",
    "active_clearance": "Maintain active participation and clear communication.",
    "obtain_clearance": "Obtain approval and maintain clear documentation.",
    "clearance_eligibility": "Eligibility rules are clear to applicants.",
}


@pytest.mark.parametrize("rule", KEYWORD_RULES, ids=lambda rule: rule.name)
def test_f_l1_001_002_and_010_every_rule_has_positive_and_negative_examples(
    rule: KeywordRule,
) -> None:
    assert rule.pattern.search(POSITIVE_EXAMPLES[rule.name])
    assert not rule.pattern.search(NEGATIVE_EXAMPLES[rule.name])


def test_f_l1_003_case_and_punctuation_variants_match() -> None:
    decision = screen_posting_text("one", "A DRUG—SCREENING requirement applies!", decided_at=NOW)

    assert decision is not None
    assert decision.outcome is ScreeningOutcome.DISQUALIFY


def test_f_l1_004_thc_is_a_bounded_term() -> None:
    assert screen_posting_text("one", "THC testing applies.", decided_at=NOW) is not None
    assert screen_posting_text("one", "TheCharlotte office.", decided_at=NOW) is None


def test_f_l1_005_006_and_008_innocent_text_passes_forward() -> None:
    text = "The security team builds clearance workflows for distributed systems."

    assert screen_posting_text("one", text, decided_at=NOW) is None


def test_f_l1_007_multiple_categories_record_all_evidence() -> None:
    decision = screen_posting_text(
        "one",
        "A drug test and an active security clearance are required.",
        decided_at=NOW,
    )

    assert decision is not None
    assert {item.category for item in decision.evidence} == {
        ScreeningCategory.DRUG_TESTING,
        ScreeningCategory.SECURITY_CLEARANCE,
    }


def test_f_l1_009_unicode_and_whitespace_normalize_consistently() -> None:
    decision = screen_posting_text(
        "one",
        "A pre—employment\n\tdrug requirement applies.",
        decided_at=NOW,
    )

    assert decision is not None
    assert decision.evidence[0].category is ScreeningCategory.DRUG_TESTING
