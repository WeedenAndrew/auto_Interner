"""A second opinion on a rewrite that already passed the deterministic gate.

`validate_rewrite` answers a narrow question exactly: did the rewrite change a
number, invent a technology, escalate a proficiency claim, add contact data, or
touch a section it may not. It cannot answer whether the result still reads as
*this* person's resume. A rewrite can satisfy every mechanical rule and still
drift -- generic where the original was specific, or reordered into a shape that
no longer matches the work described.

So this grader sits **above** the validator and never replaces it. The validator
stays the hard gate: it is free, deterministic, and cannot be argued out of a
verdict. This adds judgement the validator has no way to apply.

Two deliberate constraints:

**The grader sees only the base resume, the proposal, and the posting.** Not the
rewriter's reasoning, and not any previous feedback. A grader shown why the
rewriter believes its work is good is a grader that agrees with it.

**Failures report a category, never a specific.** The feedback fed back into the
next attempt names *what kind* of rule was broken and never which token, number
or threshold broke it. That distinction is the whole safety property: a rewriter
told "a numeric claim did not match" learns to be careful with numbers, while
one told "you changed 30% to 35%" learns to avoid the comparison. The validator
is a proxy for truthfulness, and feeding a proxy back as a reward signal teaches
a model to satisfy the proxy instead of the thing it stands for.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from auto_interner.documents.template_reader import ResumeDocument
from auto_interner.model_client import StructuredModelClient
from auto_interner.rewriting.service import ValidatedRewritePlan

GRADE_TOOL_NAME = "record_rewrite_grade"

GRADE_INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["aligned", "confidence", "concern"],
    "properties": {
        "aligned": {
            "type": "boolean",
            "description": (
                "True when the rewrite still describes the same work as the base resume."
            ),
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "concern": {
            "type": "string",
            "maxLength": 300,
            "description": "One sentence naming the category of drift, with no quoted text.",
        },
    },
}

_SYSTEM_PROMPT = """Judge whether a tailored resume still describes the same work as the base it
came from. You are reviewing, not editing: return only the required structured tool call.

Answer aligned=false only when the rewrite misrepresents the candidate -- claiming work they did
not describe, generalising a specific accomplishment into something vague, or reordering sections
so the resume no longer matches the experience it lists. Rephrasing, tightening and reordering are
expected and are not misalignment on their own.

State the category of concern in one sentence. Do not quote the resume or the posting back.
"""


class GradeResponseError(ValueError):
    """A retryable structural failure in an untrusted grading response."""

    retryable = True


@dataclass(frozen=True, slots=True)
class RewriteGrade:
    """One grader verdict on a candidate rewrite."""

    aligned: bool
    confidence: Literal["low", "medium", "high"]
    concern: str

    @property
    def rejects(self) -> bool:
        """Whether this grade should block publication.

        Low confidence never blocks, mirroring the Tier 2 screening policy: an
        uncertain judgement is not evidence, and the deterministic validator has
        already passed on everything it can actually prove.
        """
        return not self.aligned and self.confidence in {"medium", "high"}


def parse_grade(raw: object) -> RewriteGrade:
    """Validate the exact grading schema locally, as with every model response."""
    if not isinstance(raw, dict) or set(raw) != {"aligned", "confidence", "concern"}:
        raise GradeResponseError("Grade response must contain exactly the required fields")
    payload = dict(raw)
    aligned = payload["aligned"]
    confidence = payload["confidence"]
    concern = payload["concern"]
    if not isinstance(aligned, bool):
        raise GradeResponseError("aligned must be boolean")
    if confidence not in {"low", "medium", "high"}:
        raise GradeResponseError("confidence must be low, medium, or high")
    if not isinstance(concern, str) or len(concern) > 300:
        raise GradeResponseError("concern must be a bounded string")
    return RewriteGrade(
        aligned=aligned,
        confidence=confidence,
        concern=" ".join(concern.split()),
    )


def grade_rewrite(
    client: StructuredModelClient,
    document: ResumeDocument,
    plan: ValidatedRewritePlan,
    posting_text: str,
) -> RewriteGrade:
    """Ask a separate call whether a validated plan still represents the base."""
    originals = document.paragraphs_by_id
    raw = client.call_tool(
        tool_name=GRADE_TOOL_NAME,
        input_schema=GRADE_INPUT_SCHEMA,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {
                "base_resume": document.model_payload(),
                "job_posting": posting_text,
                "proposed_section_order": list(plan.section_order),
                "proposed_replacements": [
                    {
                        "was": originals[replacement.paragraph_id].model_text,
                        "becomes": replacement.replacement,
                    }
                    for replacement in plan.replacements
                    if replacement.paragraph_id in originals
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    return parse_grade(raw)
