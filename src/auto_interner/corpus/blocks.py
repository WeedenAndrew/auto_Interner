"""The verified block corpus.

Every claim a generated resume can make must already exist here, written by the
user. Nothing in this package authors a claim.

JSON is the native format so the package adds no dependency — `auto_interner`
requires only python-docx, and CLAUDE.md forbids introducing one silently. YAML
is supported when PyYAML happens to be installed, because a corpus is
hand-edited and YAML is far kinder to write.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class BlockKind(StrEnum):
    EXPERIENCE = "experience"
    PROJECT = "project"
    EDUCATION = "education"
    SKILL = "skill"


class CorpusError(ValueError):
    """The corpus is structurally invalid and must not be used."""


_METRIC_PATTERN = re.compile(
    r"(?<!\w)(?:[$€£]\s*)?\d[\d,]*(?:\.\d+)?%?(?:\s*(?:\+|x|k|m|b))?(?!\w)",
    re.IGNORECASE,
)


def normalize_tag(tag: str) -> str:
    """Canonical form so 'Node.JS' and 'node.js' unify."""
    return " ".join(tag.casefold().replace("_", " ").split())


# A posting asks for "databases"; a resume says "MongoDB". Without a notion that
# the second evidences the first, the gap report claimed a real requirement was
# unsupported when the corpus supported it plainly -- the failure that makes the
# honest-gap feature untrustworthy, because a gap list padded with false misses
# is one the user learns to ignore.
#
# Entries must be definitional, not merely adjacent. Using Linux is not evidence
# of operating-systems fundamentals, and Docker is not evidence of distributed
# systems; both were considered and left out. Widening this map beyond what is
# strictly implied would hide gaps, which is the one direction this package is
# not permitted to err in.
_EVIDENCE_FOR: dict[str, frozenset[str]] = {
    "automated testing": frozenset({"pytest", "unit testing"}),
    "caching": frozenset({"redis"}),
    "concurrency": frozenset({"threading"}),
    "containers": frozenset({"docker", "kubernetes"}),
    "data pipelines": frozenset({"airflow", "dbt", "etl", "pyspark", "spark"}),
    "databases": frozenset(
        {
            "bigquery",
            "clickhouse",
            "dynamodb",
            "elasticsearch",
            "mongodb",
            "mysql",
            "postgresql",
            "redis",
            "snowflake",
            "sql",
            "sqlalchemy",
        }
    ),
    "infrastructure": frozenset({"ansible", "kubernetes", "terraform"}),
    "machine learning": frozenset({"pytorch", "tensorflow"}),
    "message queues": frozenset({"celery", "kafka", "rabbitmq"}),
    # Mobile roles are a large slice of the feed, and "mobile development" was
    # not a term at all -- so a posting asking for iOS or Android could not see
    # a shipped Flutter app, and the one mobile project in the corpus lost the
    # page to a backend one.
    "mobile development": frozenset(
        {
            "android",
            "dart",
            "flutter",
            "ios",
            "kotlin",
            "objective-c",
            "react native",
            "swift",
        }
    ),
    "monitoring": frozenset({"grafana", "observability", "prometheus"}),
    "test automation": frozenset({"pytest", "unit testing"}),
    "version control": frozenset({"bitbucket", "git", "github", "gitlab"}),
    # The transferable skill is Git; the host is not the requirement. A posting
    # saying "comfortable using GitHub" is answered by someone who lists Git,
    # and reporting that as a gap is the kind of false miss that teaches the
    # user to stop reading the gap list.
    "github": frozenset({"git", "gitlab", "bitbucket"}),
    "web scraping": frozenset({"selenium"}),
}

SUBSUMES: dict[str, frozenset[str]] = {}
for _broad, _specifics in _EVIDENCE_FOR.items():
    for _specific in _specifics:
        SUBSUMES[_specific] = SUBSUMES.get(_specific, frozenset()) | {_broad}


def expand_tags(tags: Iterable[str]) -> frozenset[str]:
    """Add the broader terms that the given tags are direct evidence of.

    Applied at construction so every corpus gets it, whether loaded from a file
    or built in memory from a resume.
    """
    normalized = {normalize_tag(t) for t in tags}
    return frozenset(normalized).union(
        *(SUBSUMES[t] for t in normalized if t in SUBSUMES), frozenset()
    )


@dataclass(frozen=True, slots=True)
class Bullet:
    """One user-authored, user-verified claim."""

    text: str
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", expand_tags(self.tags))

    @property
    def metrics(self) -> tuple[str, ...]:
        """Numeric claims, for tamper detection by the rewriting validator."""
        return tuple(
            "".join(m.group().casefold().split()) for m in _METRIC_PATTERN.finditer(self.text)
        )

    @property
    def cost(self) -> int:
        """Approximate rendered line count, for budgeting page length."""
        return max(1, round(len(self.text) / 95))


@dataclass(frozen=True, slots=True)
class Block:
    """A coherent unit of experience: one job, one project, one degree."""

    id: str
    kind: BlockKind
    title: str
    org: str = ""
    dates: str = ""
    bullets: tuple[Bullet, ...] = ()
    tags: frozenset[str] = field(default_factory=frozenset)
    recency: int = 0
    pinned: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", expand_tags(self.tags))

    @property
    def all_tags(self) -> frozenset[str]:
        if not self.bullets:
            return self.tags
        return self.tags.union(*(b.tags for b in self.bullets))

    @property
    def header_cost(self) -> int:
        return 1


def _parse_bullet(raw: object, where: str) -> Bullet:
    if isinstance(raw, str):
        return Bullet(text=raw.strip())
    if not isinstance(raw, dict) or "text" not in raw:
        raise CorpusError(f"{where}: each bullet must be a string or have a 'text' field")
    text = str(raw["text"]).strip()
    if not text:
        raise CorpusError(f"{where}: bullet text cannot be empty")
    tags = frozenset(normalize_tag(t) for t in raw.get("tags", []) if str(t).strip())
    return Bullet(text=text, tags=tags)


def _parse_block(raw: object, index: int) -> Block:
    where = f"block[{index}]"
    if not isinstance(raw, dict):
        raise CorpusError(f"{where}: must be a mapping")
    missing = {"id", "kind", "title"} - set(raw)
    if missing:
        raise CorpusError(f"{where}: missing required field(s) {sorted(missing)}")
    try:
        kind = BlockKind(str(raw["kind"]).strip().casefold())
    except ValueError:
        valid = ", ".join(k.value for k in BlockKind)
        raise CorpusError(f"{where}: kind must be one of {valid}") from None
    return Block(
        id=str(raw["id"]).strip(),
        kind=kind,
        title=str(raw["title"]).strip(),
        org=str(raw.get("org", "")).strip(),
        dates=str(raw.get("dates", "")).strip(),
        bullets=tuple(_parse_bullet(b, where) for b in raw.get("bullets", [])),
        tags=frozenset(normalize_tag(t) for t in raw.get("tags", []) if str(t).strip()),
        recency=int(raw.get("recency", 0)),
        pinned=bool(raw.get("pinned", False)),
    )


def _read(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ModuleNotFoundError:
            raise CorpusError(
                f"{path.name} is YAML but PyYAML is not installed. "
                f"Install it, or convert the corpus to JSON."
            ) from None
        return yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorpusError(f"{path.name} is not valid JSON: {exc}") from None


def load_corpus(path: Path) -> tuple[Block, ...]:
    """Load and validate a corpus. Raises rather than silently degrading."""
    if not path.is_file():
        raise CorpusError(f"Corpus not found: {path}")
    data = _read(path)
    if not isinstance(data, dict) or "blocks" not in data:
        raise CorpusError("Corpus must be a mapping with a top-level 'blocks' list")
    raw_blocks = data["blocks"]
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise CorpusError("Corpus must contain at least one block")
    blocks = tuple(_parse_block(b, i) for i, b in enumerate(raw_blocks))
    ids = [b.id for b in blocks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise CorpusError(f"Duplicate block ids: {sorted(duplicates)}")
    return blocks
