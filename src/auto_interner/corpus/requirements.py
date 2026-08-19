"""Turn an untrusted job posting into weighted, structured requirements.

The posting is data, never instructions. Extraction here is fully deterministic
so it is inspectable and testable; an optional model layer can add requirements
but can never remove one or change its weight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum

from auto_interner.corpus.blocks import normalize_tag


class Priority(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"

    @property
    def weight(self) -> int:
        return 3 if self is Priority.REQUIRED else 1


# Recognizing a term the candidate lacks is what makes gap analysis possible,
# so this vocabulary is deliberately independent of the user's own tags.
_TOOLS: frozenset[str] = frozenset(
    {
        "airflow",
        "android",
        "ansible",
        "api design",
        "aws",
        "azure",
        "bash",
        "bigquery",
        "c",
        "c#",
        "c++",
        "ci/cd",
        "celery",
        "clickhouse",
        "cloud run",
        "dbt",
        "dart",
        "django",
        "docker",
        "dynamodb",
        "elasticsearch",
        "etl",
        "fastapi",
        "flask",
        "flutter",
        "gcp",
        "git",
        "github",
        "gitlab",
        "go",
        "grafana",
        "graphql",
        "grpc",
        "ios",
        "java",
        "javascript",
        "jenkins",
        "kafka",
        "kotlin",
        "kubernetes",
        "linux",
        "microservices",
        "mongodb",
        "mysql",
        "nginx",
        "node.js",
        "numpy",
        "objective-c",
        "observability",
        "pandas",
        "postgresql",
        "prometheus",
        "pyspark",
        "pytest",
        "python",
        "pytorch",
        "rabbitmq",
        "react",
        "react native",
        "redis",
        "rest",
        "ruby",
        "rust",
        "scala",
        "selenium",
        "snowflake",
        "spark",
        "sql",
        "sqlalchemy",
        "swift",
        "system design",
        "tensorflow",
        "terraform",
        "threading",
        "typescript",
        "unit testing",
        "vue",
        "webhooks",
    }
)

# Named tools were the whole vocabulary, which made infrastructure, reliability
# and platform postings nearly invisible: a posting can ask for high
# availability, disaster recovery and traffic routing without naming one
# product. Those roles are a large share of the listing feed, and an
# unrecognised requirement is worse than a missed one -- it does not appear in
# the gap list either, so the resume reads as a full match when it is not.
_CONCEPTS: frozenset[str] = frozenset(
    {
        "algorithms",
        "automated testing",
        "automation",
        "caching",
        "code review",
        "concurrency",
        "containers",
        "data modeling",
        "data pipelines",
        "data structures",
        "databases",
        "debugging",
        "disaster recovery",
        "distributed systems",
        "fault tolerance",
        "high availability",
        "incident response",
        "infrastructure",
        "integration testing",
        "load balancing",
        "logging",
        "app lifecycle",
        "machine learning",
        "message queues",
        "mobile development",
        "model evaluation",
        "model training",
        "monitoring",
        "networking",
        "operating systems",
        "performance tuning",
        "reliability",
        "scalability",
        "scripting",
        "site reliability",
        "software architecture",
        "test automation",
        "throughput",
        "traffic routing",
        "version control",
        "web scraping",
    }
)

TAXONOMY: frozenset[str] = _TOOLS | _CONCEPTS

# A term ends where an identifier could not continue. The dot is the awkward
# case: it is part of "node.js" but is also how a sentence ends, and excluding
# it outright made "Experience with Docker." extract nothing at all. Postings
# put the skill that matters at the end of the sentence constantly, so this
# silently dropped real requirements and shrank the reported gap list -- the
# one direction this module is not allowed to err in.
_TERM_END = r"(?![\w+#-])(?!\.\w)"

_REQUIRED_CUES = (
    "required",
    "requirement",
    "must have",
    "must be",
    "minimum",
    "you have",
    "we require",
    "essential",
    "qualifications",
)
_PREFERRED_CUES = (
    "preferred",
    "nice to have",
    "nice-to-have",
    "bonus",
    "a plus",
    "plus if",
    "desirable",
    "ideally",
    "helpful",
)


@dataclass(frozen=True, slots=True)
class Requirement:
    """One extracted, weighted thing the posting asks for."""

    term: str
    priority: Priority
    evidence: str
    group: str = ""

    @property
    def weight(self) -> int:
        return self.priority.weight

    @property
    def key(self) -> str:
        """What this requirement counts as. Alternates share one key."""
        return self.group or self.term


# "One or more languages such as Java, Go, C++, or Python" is a single
# requirement with four acceptable answers, not four requirements. Treating it
# as four inflated the gap list with things the candidate does not need: a
# Python programmer was told they were missing Go and C++ by the same posting
# that said Python was fine. A gap list padded with false misses is one the user
# stops reading.
#
# The cue must be alternation, not enumeration. "Data structures, algorithms,
# operating systems, networking, and databases" is a conjunction -- all of it is
# wanted -- and stays separate.
_ALTERNATION_CUES = ("one or more", "such as", "and/or", " or ")


_REQUIRED_HEADERS = (
    "requirement",
    "qualification",
    "must have",
    "what you",
    "you have",
    "minimum",
    "basic qualification",
    "responsibilities",
    "essential",
)
_PREFERRED_HEADERS = (
    "nice to have",
    "nice-to-have",
    "preferred",
    "bonus",
    "plus",
    "desirable",
    "good to have",
    "optional",
)


def _is_header(line: str) -> Priority | None:
    """A short line naming a qualification block, with or without a colon.

    Requiring a trailing ':' missed the "Preferred Qualifications" style used
    by most large employers, so every optional skill inherited the previous
    section and was reported as required. That is the expensive direction of
    the error: it turns a near-fit into a document full of manufactured gaps.

    A colonless line must look like a heading rather than a sentence -- few
    words, no internal punctuation, and no skill term of its own -- so that
    "Preferred experience with Kafka" stays a requirement instead of being
    swallowed as a header and dropped.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 60:
        return None
    if stripped.endswith(":"):
        candidate = stripped
    else:
        words = stripped.split()
        if len(words) > 4 or any(character in stripped for character in ",.;"):
            return None
        lowered_line = stripped.casefold()
        if any(
            re.search(rf"(?<![\w.+#-]){re.escape(term)}{_TERM_END}", lowered_line)
            for term in TAXONOMY
        ):
            return None
        candidate = stripped
    lowered = candidate.casefold()
    if any(cue in lowered for cue in _PREFERRED_HEADERS):
        return Priority.PREFERRED
    if any(cue in lowered for cue in _REQUIRED_HEADERS):
        return Priority.REQUIRED
    return None


@dataclass(frozen=True, slots=True)
class _Segment:
    text: str
    section: Priority


def _segments(text: str) -> list[_Segment]:
    """Split into sentences, carrying the governing section priority forward.

    A posting's "Nice to have:" header applies until the next header. Scoping
    priority to the line alone was wrong: it marked every optional skill
    required, which inflated the gap list and made near-fits look like misses.
    """
    parts: list[_Segment] = []
    section = Priority.REQUIRED
    buffer: list[str] = []

    def flush(current: Priority) -> None:
        if not buffer:
            return
        joined = " ".join(buffer)
        buffer.clear()
        for sentence in re.split(r"(?<=[.;])\s+", joined):
            sentence = sentence.strip()
            if sentence:
                parts.append(_Segment(sentence, current))

    for raw_line in text.splitlines():
        header = _is_header(raw_line)
        if header is not None:
            flush(section)
            section = header
            continue
        stripped = raw_line.strip()
        if not stripped:
            flush(section)
            continue
        # A bullet marker starts a new requirement. Anything else is the same
        # one continuing: postings wrap, and splitting on the newline separated
        # "one or more languages, including" from the languages themselves, so
        # the alternation was invisible and every option became its own gap.
        if raw_line.lstrip()[:1] in {"-", "*", "\u2022"}:
            flush(section)
        buffer.append(stripped.strip(" \t-*\u2022"))
    flush(section)
    return parts


def _priority_for(segment: _Segment) -> Priority:
    """Inline cues override the section they sit in."""
    tail = segment.text.casefold()
    if any(cue in tail for cue in _PREFERRED_CUES):
        return Priority.PREFERRED
    if any(cue in tail for cue in _REQUIRED_CUES):
        return Priority.REQUIRED
    return segment.section


def extract_requirements(
    posting_text: str, vocabulary: frozenset[str] | None = None
) -> tuple[Requirement, ...]:
    """Extract weighted requirements from posting text.

    A term found in both a required and a preferred context resolves to
    required: over-stating what the posting demands is the safe direction,
    because it can only widen the reported gap list.
    """
    vocab = vocabulary or TAXONOMY
    found: dict[str, Requirement] = {}
    for segment in _segments(posting_text):
        priority = _priority_for(segment)
        lowered = segment.text.casefold()
        matched = [
            normalize_tag(term)
            for term in vocab
            if re.search(rf"(?<![\w.+#-]){re.escape(term)}{_TERM_END}", lowered)
        ]
        group = ""
        if len(matched) > 1 and any(cue in lowered for cue in _ALTERNATION_CUES):
            group = "either " + " / ".join(sorted(matched))
        for key in matched:
            existing = found.get(key)
            if existing is None:
                found[key] = Requirement(
                    term=key, priority=priority, evidence=segment.text[:200], group=group
                )
                continue
            # Priority and grouping are upgraded independently. Bailing out on
            # the first sighting meant a term already seen ungrouped could never
            # join a later alternation, so the group ended up holding fewer
            # members than its own label named -- and was reported unsatisfied
            # while one of the terms it listed was plainly covered.
            upgraded = existing.priority is Priority.PREFERRED and priority is Priority.REQUIRED
            new_priority = priority if upgraded else existing.priority
            new_group = existing.group or group
            if new_priority is existing.priority and new_group == existing.group:
                continue
            found[key] = replace(
                existing,
                priority=new_priority,
                group=new_group,
                evidence=segment.text[:200] if upgraded else existing.evidence,
            )
    return tuple(sorted(found.values(), key=lambda r: (-r.weight, r.term)))
