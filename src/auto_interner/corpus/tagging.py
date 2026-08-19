"""Derive requirement tags from what the user already wrote.

A posting asks for "code review". A resume says *"flag coding discrepancies and
issues"*. Those are the same work described in different words, and matching on
the literal term alone reported it as a gap.

This is deliberately a *tagging* layer and not a rewriting one. The resume text
is never touched, never paraphrased, never regenerated. All that widens is what
an existing sentence is understood to count as. The distinction matters: writing
"Performed code review" for someone who did not write it is a fabricated claim,
while recognising that the sentence they did write demonstrates code review is
reading, which is what a human screener does anyway.

Because that reading can be wrong, every tag carries the exact substring that
earned it. A phrase tag the user disagrees with is visible and removable rather
than silently inflating their coverage -- the failure mode that would make this
layer worse than not having it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from auto_interner.corpus.blocks import expand_tags, normalize_tag
from auto_interner.corpus.requirements import TAXONOMY


@dataclass(frozen=True, slots=True)
class TagHit:
    """One tag, and the words in the user's own text that produced it."""

    tag: str
    matched: str
    rule: str

    def describe(self) -> str:
        return f"{self.tag} <- {self.rule}: “{self.matched}”"


# Phrase rules. Each maps evidence a person actually writes on a resume to the
# capability a posting actually names.
#
# The bar is that the user could defend the tag in an interview using only the
# sentence that triggered it. "Automated restarts, monitoring, recovery
# procedures" earns `reliability` and `infrastructure` on that test. It does not
# earn `disaster recovery` or `high availability`, which mean multi-region
# failover to the teams that ask for them, and those stay gaps. Over-tagging
# here would hide real gaps, and a gap list that flatters is the one failure
# this package cannot absorb.
PHRASE_RULES: tuple[tuple[str, frozenset[str]], ...] = (
    (r"code review(?:s|ed|ing)?", frozenset({"code review"})),
    (r"pull requests?", frozenset({"code review", "version control"})),
    (
        r"(?:flag(?:ged|ging)?|caught|identif(?:y|ied)|review(?:ed)?)\s+"
        r"(?:\w+\s+){0,3}?(?:cod(?:e|ing)|implementation)\s+"
        r"(?:discrepanc\w*|issues?|errors?|bugs?|defects?)",
        frozenset({"code review", "debugging"}),
    ),
    (r"root caus\w+|triag\w+|diagnos\w+", frozenset({"debugging"})),
    # Alternations run longest-first so the reported evidence is the whole word.
    # "deployment" matching as "deploy" makes the provenance line read like the
    # rule fired on something the user did not quite write.
    (r"deploy(?:ments|ment|ing|ed)?", frozenset({"infrastructure"})),
    (r"self-?hosted|bare metal|provision(?:ed|ing)?", frozenset({"infrastructure"})),
    (r"docker|container(?:s|ised|ized)?", frozenset({"containers", "infrastructure"})),
    (r"ci/cd|continuous integration|build pipeline", frozenset({"ci/cd", "automation"})),
    (r"monitor(?:s|ed|ing)?|health ?check\w*|heartbeat|alerting", frozenset({"monitoring"})),
    (
        r"automated restarts?|recovery procedures?|self-?healing|fault[- ]toleran\w+"
        r"|graceful (?:shutdown|degradation)|retry|retries",
        frozenset({"reliability"}),
    ),
    (r"automat(?:ically|ion|ing|es|ed|e)", frozenset({"automation"})),
    (
        r"unit tests?|integration tests?|test suites?|regression tests?",
        frozenset({"automated testing", "test automation"}),
    ),
    (r"data pipelines?|etl\b", frozenset({"data pipelines"})),
    (r"mobile|android|ios\b|app store|play store|on-device", frozenset({"mobile development"})),
    (r"scrap(?:ing|er|ed|e)|crawl(?:ing|er|ed)?", frozenset({"web scraping"})),
    (r"\bgit\b|github|branch(?:es|ing)?|version control", frozenset({"version control"})),
    (r"concurren\w+|multithread\w+|thread(?:s|ing|ed)\b|async\w*", frozenset({"concurrency"})),
    (r"cach(?:ing|es|ed|e)", frozenset({"caching"})),
    (r"schema|data model(?:s|ling|ing)?", frozenset({"data modeling"})),
    (r"latency|throughput|profil(?:e|ed|ing)|optimi[sz]\w+", frozenset({"performance tuning"})),
)

_COMPILED: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), tags) for pattern, tags in PHRASE_RULES
)


def _term_hits(text: str) -> list[TagHit]:
    """Literal taxonomy terms, the original and still primary signal."""
    hits: list[TagHit] = []
    lowered = text.casefold()
    for term in TAXONOMY:
        match = re.search(rf"(?<![\w.+#-]){re.escape(term)}(?![\w+#-])(?!\.\w)", lowered)
        if match:
            hits.append(TagHit(normalize_tag(term), match.group(), "term"))
    return hits


def tag_text(text: str, *, phrases: bool = True) -> tuple[frozenset[str], tuple[TagHit, ...]]:
    """Return the tags this text supports, and why each one was applied.

    `phrases=False` restores literal-term-only behaviour, which is what the
    conservative path and the regression tests use.
    """
    hits = _term_hits(text)
    if phrases:
        for pattern, tags in _COMPILED:
            match = pattern.search(text)
            if match is None:
                continue
            for tag in tags:
                hits.append(TagHit(tag, match.group(), "phrase"))

    direct = frozenset(hit.tag for hit in hits)
    resolved = expand_tags(direct)
    for implied in sorted(resolved - direct):
        hits.append(TagHit(implied, "", "implied"))
    return resolved, tuple(hits)


def explain(text: str) -> str:
    """Human-readable provenance for every tag, for auditing a corpus."""
    _, hits = tag_text(text)
    if not hits:
        return "no tags"
    return "\n".join(sorted(hit.describe() for hit in hits))
