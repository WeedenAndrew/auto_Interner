"""Report what the posting asked for, what you showed, and what you lack.

Competing tools close a gap by inventing experience. This one names the gap.
That is the honest answer and the useful one: a named gap is either a real
reason not to apply, or a prompt to add something true to the corpus.
"""

from __future__ import annotations

from dataclasses import dataclass

from auto_interner.corpus.blocks import Block
from auto_interner.corpus.requirements import Priority, Requirement
from auto_interner.corpus.selection import Selection


@dataclass(frozen=True, slots=True)
class RequirementStatus:
    requirement: Requirement
    shown_in: tuple[str, ...]  # block ids surfaced in this render
    available_in: tuple[str, ...]  # block ids in the corpus that could cover it

    @property
    def is_shown(self) -> bool:
        return bool(self.shown_in)

    @property
    def is_gap(self) -> bool:
        """Nothing in the entire corpus truthfully supports this requirement."""
        return not self.available_in

    @property
    def is_missed(self) -> bool:
        """You can support it, but the budget squeezed it out of this render."""
        return bool(self.available_in) and not self.shown_in


@dataclass(frozen=True, slots=True)
class CoverageReport:
    statuses: tuple[RequirementStatus, ...]

    @property
    def gaps(self) -> tuple[RequirementStatus, ...]:
        return tuple(s for s in self.statuses if s.is_gap)

    @property
    def missed(self) -> tuple[RequirementStatus, ...]:
        return tuple(s for s in self.statuses if s.is_missed)

    @property
    def shown(self) -> tuple[RequirementStatus, ...]:
        return tuple(s for s in self.statuses if s.is_shown)

    def _groups(self) -> tuple[tuple[str, tuple[RequirementStatus, ...]], ...]:
        """Statuses bucketed by what they count as.

        Alternates ("Java, Go, C++, or Python") share one key and are satisfied
        together the moment any one of them is shown. Everything else is its own
        singleton, so ungrouped behaviour is unchanged.
        """
        buckets: dict[str, list[RequirementStatus]] = {}
        for status in self.statuses:
            buckets.setdefault(status.requirement.key, []).append(status)
        return tuple((key, tuple(group)) for key, group in buckets.items())

    def satisfied_groups(self) -> tuple[str, ...]:
        return tuple(k for k, g in self._groups() if any(s.is_shown for s in g))

    def unsatisfied_groups(self) -> tuple[str, ...]:
        """Requirements with nothing behind them, counted once per alternation."""
        return tuple(
            k
            for k, g in self._groups()
            if not any(s.is_shown for s in g) and all(s.is_gap for s in g)
        )

    def score(self) -> float:
        """Fraction of total requirement weight surfaced, 0.0-1.0.

        Read this for one posting only. Its denominator is however many terms
        that posting happened to name, which is a fact about the writing and not
        about the candidate -- see `is_comparable`.
        """
        total = sum(max(s.requirement.weight for s in group) for _, group in self._groups())
        if not total:
            return 1.0
        return self.evidence() / total

    def evidence(self) -> int:
        """Requirement weight actually surfaced. Absolute, not a ratio.

        Ranking a feed by `score` rewards vague postings and punishes precise
        ones, because the denominator is the posting's specificity. Measured
        across five live listings, a posting naming two skills of which the
        candidate had one scored 50%, while one naming sixteen of which they
        held four scored 27% -- ordering the weaker match first on strictly less
        evidence. This is the number to sort a feed by.
        """
        return sum(
            max(s.requirement.weight for s in group)
            for _, group in self._groups()
            if any(s.is_shown for s in group)
        )

    def is_comparable(self, minimum: int = 5) -> bool:
        """Whether `score` means enough to set beside another posting's.

        Below a handful of extracted requirements the ratio is dominated by how
        the posting was written, and a single term swings it by tens of points.
        """
        return len(self._groups()) >= minimum

    def required_gaps(self) -> tuple[RequirementStatus, ...]:
        return tuple(s for s in self.gaps if s.requirement.priority is Priority.REQUIRED)


def build_report(
    blocks: tuple[Block, ...],
    requirements: tuple[Requirement, ...],
    selection: Selection,
) -> CoverageReport:
    shown_by: dict[str, list[str]] = {}
    for sel in selection.blocks:
        for term in sel.covers:
            shown_by.setdefault(term, []).append(sel.block.id)

    statuses = []
    for req in requirements:
        available = tuple(b.id for b in blocks if req.term in b.all_tags)
        statuses.append(
            RequirementStatus(
                requirement=req,
                shown_in=tuple(dict.fromkeys(shown_by.get(req.term, ()))),
                available_in=available,
            )
        )
    return CoverageReport(tuple(statuses))
