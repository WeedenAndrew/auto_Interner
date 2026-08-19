"""Choose which verified blocks and bullets to show for a given posting.

Tailoring is a selection problem, not a generation problem. Maximizing covered
requirement weight under a length budget is the classic maximum-coverage
problem: the objective is submodular, so the greedy rule below is within
(1 - 1/e) of optimal and, unlike a model's judgment, it can be explained line
by line. Every selected bullet records exactly which requirements justified it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from auto_interner.corpus.blocks import Block, BlockKind, Bullet
from auto_interner.corpus.requirements import Requirement


@dataclass(frozen=True, slots=True)
class SelectedBullet:
    bullet: Bullet
    covers: frozenset[str]


@dataclass(frozen=True, slots=True)
class SelectedBlock:
    block: Block
    bullets: tuple[SelectedBullet, ...]
    header_covers: frozenset[str]
    marginal_weight: int
    cost: int

    @property
    def covers(self) -> frozenset[str]:
        return (
            self.header_covers.union(*(b.covers for b in self.bullets))
            if self.bullets
            else self.header_covers
        )


@dataclass(frozen=True, slots=True)
class Shape:
    """Structural minimums a resume must meet regardless of the posting.

    Coverage optimisation answers "what does this employer want to see". It
    does not answer "what must a resume contain to be a resume", and those are
    different questions with different failure modes.

    No posting lists a degree as a requirement, so education scores zero on
    coverage and gets dropped — from an internship application, where its
    absence is disqualifying. Likewise a single job reads as no history.

    These are satisfied first and consume budget before coverage runs.
    """

    min_experience: int = 2
    complete_kinds: frozenset[str] = field(default_factory=lambda: frozenset({"education"}))
    """Kinds included in full — every block, every bullet, never trimmed."""

    max_blocks_by_kind: dict[str, int] = field(default_factory=lambda: {"project": 2})
    """How many blocks of this kind may appear at all.

    Filling the page to the last line is not the same as making it good. Once
    the budget was set from real page capacity, every project in the corpus fit
    — and a résumé listing five projects reads as a list of hobbies rather than
    a claim about what the person is best at.

    Three fit the estimate and still spilled in Word, where the last project's
    second bullet landed alone on page two. Two is what actually holds, and two
    strong entries beat three that force a reader to turn a page for one line.

    It is also what restores curation: with room for everything, nothing
    competes, and the two postings produced near-identical documents again.
    """

    bullets_by_kind: dict[str, int] = field(default_factory=lambda: {"project": 2})
    """Bullets a block of this kind shows — both floor and ceiling.

    Coverage alone gives projects a ragged shape: one earns four bullets, the
    next renders as a bare title because its second bullet covered nothing new.
    That reads as an abandoned entry rather than a deliberate one. Two is the
    number that looks intentional -- enough to say what a thing is and one
    concrete detail -- and holding every project to it makes the section scan.

    A block with only one bullet still shows one. This forces a floor, not
    padding, because there is nothing to pad with.
    """

    fill_target: float = 0.85
    """Fraction of the budget a finished page should occupy.

    A resume that stops two thirds down the page reads as a thin resume, and no
    amount of typesetting hides it. When the corpus cannot reach this, that is
    worth saying out loud rather than padding — the remedy is more verified
    blocks, not wider margins.
    """


@dataclass(frozen=True, slots=True)
class Selection:
    blocks: tuple[SelectedBlock, ...]
    covered: frozenset[str]
    budget: int
    used: int = 0
    fill_target: float = 0.85

    @property
    def remaining(self) -> int:
        return self.budget - self.used

    @property
    def utilization(self) -> float:
        return self.used / self.budget if self.budget else 1.0

    @property
    def underfilled(self) -> bool:
        """True when the corpus ran out before the page did."""
        return self.utilization < self.fill_target

    def fill_report(self) -> str:
        pct = self.utilization
        if not self.underfilled:
            return f"page {pct:.0%} full ({self.used}/{self.budget} lines)"
        short = int(self.budget * self.fill_target) - self.used
        return (
            f"page only {pct:.0%} full ({self.used}/{self.budget} lines) — "
            f"about {short} lines short. The corpus is exhausted, not the page: "
            f"every verified block was used. Add blocks to fill it."
        )


def _plan_block(
    block: Block,
    requirements: dict[str, Requirement],
    already_covered: frozenset[str],
    max_bullets: int,
    budget: int,
    required_bullets: int = 0,
) -> SelectedBlock | None:
    """Greedily choose this block's bullets by marginal requirement coverage.

    Block-level tags are credited once, to the header. Attributing them to every
    bullet was a bug: the first bullet appeared to cover the block's entire tag
    set, every later bullet scored zero marginal gain, and blocks rendered with
    a single line while most of the page budget went unused.
    """
    terms = set(requirements)
    cost = block.header_cost
    if cost > budget:
        return None

    header_covers = frozenset(block.tags & terms - already_covered)
    covered = set(already_covered) | header_covers
    weight = sum(requirements[t].weight for t in header_covers)

    if required_bullets:
        # Both floor and ceiling. A section where one entry shows two bullets
        # and the next shows three is not uniform, and the fill pass was happily
        # deepening one project past the others to spend leftover budget.
        max_bullets = min(max_bullets, required_bullets)

    remaining = list(block.bullets)
    order = {bullet: index for index, bullet in enumerate(block.bullets)}
    chosen: list[SelectedBullet] = []
    while remaining and len(chosen) < max_bullets:
        best: tuple[tuple[int, int, int], Bullet] | None = None
        for bullet in remaining:
            if cost + bullet.cost > budget:
                continue
            hits = bullet.tags & terms - covered
            gain = sum(requirements[t].weight for t in hits)
            # Ties broke on -cost, so the shorter bullet won. That is length,
            # not fit: on a reliability posting it happened to keep the right
            # bullet, but only by accident, and the opposite accident is equally
            # likely. Rank instead by how much of the posting the bullet speaks
            # to at all -- including ground already covered, since restating a
            # required skill in a second context is corroboration -- and fall
            # back to the order the user wrote them in, which is their own
            # judgment about what matters most.
            affinity = len(bullet.tags & terms)
            candidate = (gain, affinity, -order[bullet])
            if best is None or candidate > best[0]:
                best = (candidate, bullet)
        if best is None:
            break
        (gain, _, _), bullet = best
        # One bullet minimum so a selected block never renders as a bare header,
        # plus whatever floor the shape sets for this kind; past that, stop as
        # soon as a bullet earns nothing new.
        floor_for_kind = max(1, min(required_bullets, len(block.bullets)))
        if gain == 0 and len(chosen) >= floor_for_kind:
            break
        hits = frozenset(bullet.tags & terms - covered)
        chosen.append(SelectedBullet(bullet, hits))
        covered |= hits
        weight += gain
        cost += bullet.cost
        remaining.remove(bullet)

    # A skills line is a header and nothing else, so it is selectable on that
    # header alone provided it covers something. No other kind is: a job or
    # project with no bullets is an unfinished entry, and putting its bare title
    # on the page looks worse than omitting it. Allowing any bulletless block
    # here let a stub project outbid a real one on cost, because a header is
    # cheaper than a header plus evidence.
    if (
        not chosen
        and not block.bullets
        and (block.kind is not BlockKind.SKILL or not header_covers)
    ):
        return None
    if not chosen and block.bullets and not header_covers:
        return None

    return SelectedBlock(block, tuple(chosen), header_covers, weight, cost)


def select(
    blocks: tuple[Block, ...],
    requirements: tuple[Requirement, ...],
    budget: int = 34,
    max_bullets_per_block: int = 4,
    shape: Shape | None = None,
) -> Selection:
    """Select blocks maximizing covered requirement weight within `budget` lines.

    Structural minimums (`shape`) are satisfied first and are not negotiable
    against coverage — see `Shape`.
    """
    shape = shape or Shape()
    req_index = {r.term: r for r in requirements}
    covered: frozenset[str] = frozenset()
    selected: list[SelectedBlock] = []
    used = 0
    pool = list(blocks)

    # --- structural minimums, before anything competes on coverage ---------
    def take(block: Block, all_bullets: bool) -> None:
        nonlocal used, covered
        terms = set(req_index)
        cost = block.header_cost
        chosen: list[SelectedBullet] = []
        limit = len(block.bullets) if all_bullets else max_bullets_per_block
        for bullet in block.bullets[:limit]:
            chosen.append(SelectedBullet(bullet, frozenset(bullet.tags & terms - covered)))
            cost += bullet.cost
        selected.append(SelectedBlock(block, tuple(chosen), frozenset(), 0, cost))
        if chosen:
            covered |= frozenset().union(*(b.covers for b in chosen))
        used += cost
        pool.remove(block)

    for block in [b for b in pool if b.kind.value in shape.complete_kinds]:
        take(block, all_bullets=True)

    experience = sorted(
        [b for b in pool if b.kind.value == "experience"],
        key=lambda b: -b.recency,
    )
    for block in experience[: shape.min_experience]:
        take(block, all_bullets=False)

    # Pinned blocks are structural (current role, degree) and bypass scoring.
    for block in [b for b in pool if b.pinned]:
        plan = _plan_block(
            block,
            req_index,
            covered,
            max_bullets_per_block,
            budget - used,
            shape.bullets_by_kind.get(block.kind.value, 0),
        )
        pool.remove(block)
        if plan is None:
            continue
        selected.append(plan)
        covered |= plan.covers
        used += plan.cost

    def at_capacity(kind: str) -> bool:
        limit = shape.max_blocks_by_kind.get(kind)
        if limit is None:
            return False
        return sum(1 for s in selected if s.block.kind.value == kind) >= limit

    while pool and used < budget:
        best: SelectedBlock | None = None
        best_key: tuple[float, int] | None = None
        for block in pool:
            if at_capacity(block.kind.value):
                continue
            plan = _plan_block(
                block,
                req_index,
                covered,
                max_bullets_per_block,
                budget - used,
                shape.bullets_by_kind.get(block.kind.value, 0),
            )
            if plan is None or plan.marginal_weight <= 0:
                continue
            key = (plan.marginal_weight / plan.cost, block.recency)
            if best_key is None or key > best_key:
                best, best_key = plan, key
        if best is None:
            break
        selected.append(best)
        covered |= best.covers
        used += best.cost
        pool.remove(best.block)

    selected, used = _fill(
        selected,
        pool,
        req_index,
        covered,
        budget,
        used,
        max_bullets_per_block,
        bullets_by_kind=shape.bullets_by_kind,
        max_blocks_by_kind=shape.max_blocks_by_kind,
    )

    order = {"experience": 0, "project": 1, "skill": 2, "education": 3}
    selected.sort(key=lambda s: (order.get(s.block.kind.value, 9), -s.block.recency))
    return Selection(tuple(selected), covered, budget, used, shape.fill_target)


def _affinity(tags: frozenset[str], requirements: dict[str, Requirement]) -> int:
    """Relevance to the posting, ignoring whether a term is already covered.

    Coverage answers "what must appear". Affinity answers "what earns the
    leftover space". Without this second pass the resume stops the instant every
    requirement is satisfied, leaving most of the page blank and most of the
    corpus unused - correct as maximum-coverage, useless as a document.
    """
    return sum(requirements[t].weight for t in tags & set(requirements))


def _fill(
    selected: list[SelectedBlock],
    pool: list[Block],
    requirements: dict[str, Requirement],
    covered: frozenset[str],
    budget: int,
    used: int,
    max_bullets: int,
    bullets_by_kind: dict[str, int] | None = None,
    max_blocks_by_kind: dict[str, int] | None = None,
) -> tuple[list[SelectedBlock], int]:
    """Spend leftover budget on the most on-topic remaining content."""
    bullets_by_kind = bullets_by_kind or {}
    max_blocks_by_kind = max_blocks_by_kind or {}
    while used < budget:
        best_kind: str | None = None
        best_score: tuple[int, int] | None = None
        best_payload = None

        # Option A: deepen a block already on the page.
        for index, sel in enumerate(selected):
            exact = bullets_by_kind.get(sel.block.kind.value)
            ceiling = min(max_bullets, exact) if exact else max_bullets
            if len(sel.bullets) >= ceiling:
                continue
            shown = {b.bullet for b in sel.bullets}
            for bullet in sel.block.bullets:
                if bullet in shown or used + bullet.cost > budget:
                    continue
                score = (_affinity(bullet.tags, requirements), sel.block.recency)
                if best_score is None or score > best_score:
                    best_kind, best_score, best_payload = "bullet", score, (index, bullet)

        # Option B: introduce a new block.
        for block in pool:
            limit = max_blocks_by_kind.get(block.kind.value)
            if (
                limit is not None
                and sum(1 for s in selected if s.block.kind.value == block.kind.value) >= limit
            ):
                continue
            plan = _plan_block(
                block,
                requirements,
                covered,
                max_bullets,
                budget - used,
                bullets_by_kind.get(block.kind.value, 0),
            )
            if plan is None:
                # _plan_block rejects zero-coverage blocks; build a header-only
                # fallback so a relevant block can still enter on affinity.
                if used + block.header_cost > budget:
                    continue
                if not block.bullets:
                    # A skills line is a header and nothing else. Requiring a
                    # bullet here meant it could never be filled in, so a resume
                    # that had room went out without its skills section while
                    # reporting the corpus exhausted.
                    #
                    # Only for skills. A job or project with no bullets is not a
                    # self-contained line, it is an unfinished entry -- allowing
                    # those in put a bare project title back on the page with
                    # nothing under it, which is the defect this whole pass was
                    # meant to remove.
                    if block.kind is not BlockKind.SKILL:
                        continue
                    plan = SelectedBlock(block, (), frozenset(), 0, block.header_cost)
                else:
                    first = block.bullets[0]
                    if used + block.header_cost + first.cost > budget:
                        continue
                    plan = SelectedBlock(
                        block,
                        (SelectedBullet(first, frozenset()),),
                        frozenset(),
                        0,
                        block.header_cost + first.cost,
                    )
            score = (_affinity(block.all_tags, requirements), block.recency)
            if best_score is None or score > best_score:
                best_kind, best_score, best_payload = "block", score, plan

        if best_payload is None or best_score is None or best_score[0] <= 0:
            break

        if best_kind == "bullet":
            index, bullet = best_payload
            sel = selected[index]
            hits = frozenset(bullet.tags & set(requirements) - covered)
            selected[index] = SelectedBlock(
                sel.block,
                sel.bullets + (SelectedBullet(bullet, hits),),
                sel.header_covers,
                sel.marginal_weight,
                sel.cost + bullet.cost,
            )
            covered |= hits
            used += bullet.cost
        else:
            plan = best_payload
            selected.append(plan)
            covered |= plan.covers
            used += plan.cost
            pool.remove(plan.block)

    return _fill_by_recency(
        selected,
        pool,
        requirements,
        covered,
        budget,
        used,
        max_bullets,
        bullets_by_kind,
        max_blocks_by_kind,
    )


def _fill_by_recency(
    selected: list[SelectedBlock],
    pool: list[Block],
    requirements: dict[str, Requirement],
    covered: frozenset[str],
    budget: int,
    used: int,
    max_bullets: int,
    bullets_by_kind: dict[str, int] | None = None,
    max_blocks_by_kind: dict[str, int] | None = None,
) -> tuple[list[SelectedBlock], int]:
    """Last resort: spend remaining budget on the most recent unselected blocks.

    Affinity fill stops when nothing left overlaps the posting. On a resume that
    is the wrong place to stop — it leaves two thirds of the page blank while
    real experience sits unselected, because the bullets happen to describe what
    was done rather than which library did it.

    A relevant-looking blank half-page is worse than a true block the posting did
    not happen to ask for. Education is the clearest case: no posting lists it as
    a requirement, and omitting it from an internship resume is disqualifying.
    """
    terms = set(requirements)
    bullets_by_kind = bullets_by_kind or {}
    max_blocks_by_kind = max_blocks_by_kind or {}
    for block in sorted(pool, key=lambda b: -b.recency):
        if used >= budget:
            break
        # This is the third and last place blocks can enter, and it was the only
        # one not honouring the shape caps -- so six projects reached the page
        # through it while the two passes above were correctly holding three.
        limit = max_blocks_by_kind.get(block.kind.value)
        if (
            limit is not None
            and sum(1 for s in selected if s.block.kind.value == block.kind.value) >= limit
        ):
            continue
        exact = bullets_by_kind.get(block.kind.value)
        ceiling = min(max_bullets, exact) if exact else max_bullets
        cost = block.header_cost
        chosen: list[SelectedBullet] = []
        for bullet in block.bullets:
            if len(chosen) >= ceiling or used + cost + bullet.cost > budget:
                break
            chosen.append(SelectedBullet(bullet, frozenset(bullet.tags & terms - covered)))
            cost += bullet.cost
        if not chosen:
            continue
        selected.append(SelectedBlock(block, tuple(chosen), frozenset(), 0, cost))
        covered |= frozenset().union(*(b.covers for b in chosen))
        used += cost
    return selected, used
