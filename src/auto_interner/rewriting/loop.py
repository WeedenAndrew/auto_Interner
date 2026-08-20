"""Bounded retry of a rewrite against both gates, with category-only feedback.

A single rewrite attempt either satisfies the deterministic validator and the
grader or it does not, and a first attempt that misses by one rule is common
enough to be worth one more try. This runs that retry and nothing more.

**One budget, shared.** `MAX_ATTEMPTS` counts attempts, not failures per gate. A
validator rejection and a grader rejection draw from the same pool, so the worst
case per listing is a fixed, knowable number of calls: two rewrites and two
grades. Separate budgets per gate would let a rewrite that fails each gate
alternately run twice as long for no better outcome.

**Feedback carries a category, never a specific.** Every message fed back names
the kind of rule broken. The validator's own messages are already written that
way -- "changed or introduced a numeric claim", not "changed 30% to 35%" -- so
they pass through unmodified, and the grader is instructed to answer in the same
register. See `grading` for why that distinction is the point rather than a
nicety.

**Exhaustion is terminal, and honest about it.** When the budget runs out the
last failure is raised as `UnsupportedRewriteError`, which the pipeline already
routes to a permanent outcome rather than a retry. Trying again on the next
cycle would spend the same calls on the same posting to reach the same place.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from auto_interner.documents.template_reader import ResumeDocument
from auto_interner.model_client import StructuredModelClient
from auto_interner.rewriting.grading import RewriteGrade, grade_rewrite
from auto_interner.rewriting.service import (
    UnsupportedRewriteError,
    ValidatedRewritePlan,
    request_validated_rewrite,
)

# Two attempts, shared across both gates. A third has never been the difference
# between a usable resume and an unusable one; it is the difference between one
# wasted pair of calls and two.
MAX_ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class RewriteAttempt:
    """What one pass through both gates produced, for the failure record."""

    attempt: int
    gate: str
    category: str


@dataclass(frozen=True, slots=True)
class GradedRewrite:
    """An accepted plan plus everything rejected on the way to it."""

    plan: ValidatedRewritePlan
    grade: RewriteGrade | None
    attempts: int
    rejected: tuple[RewriteAttempt, ...] = field(default_factory=tuple)


def request_graded_rewrite(
    client: StructuredModelClient,
    document: ResumeDocument,
    posting_text: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
) -> GradedRewrite:
    """Rewrite, validate, grade, and retry once with category-only feedback.

    Raises `UnsupportedRewriteError` when the budget is exhausted, carrying the
    accumulated categories so the failure record explains what kept failing
    without repeating what the model actually wrote.
    """
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")

    rejected: list[RewriteAttempt] = []
    feedback: str | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            plan = request_validated_rewrite(client, document, posting_text, feedback=feedback)
        except UnsupportedRewriteError as exc:
            # Already category-level by construction; safe to hand back verbatim.
            category = str(exc)
            rejected.append(RewriteAttempt(attempt=attempt, gate="validator", category=category))
            feedback = category
            continue

        grade = grade_rewrite(client, document, plan, posting_text)
        if not grade.rejects:
            return GradedRewrite(
                plan=plan,
                grade=grade,
                attempts=attempt,
                rejected=tuple(rejected),
            )
        rejected.append(RewriteAttempt(attempt=attempt, gate="grader", category=grade.concern))
        feedback = grade.concern

    summary = "; ".join(f"attempt {item.attempt} {item.gate}: {item.category}" for item in rejected)
    raise UnsupportedRewriteError(
        f"Rewrite rejected on every one of {max_attempts} attempts -- {summary}"
    )
