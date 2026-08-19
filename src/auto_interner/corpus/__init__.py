"""Corpus-based resume tailoring: selection instead of generation.

The rewriting pipeline in `auto_interner.rewriting` validates model output
after the fact — reject any rewrite that alters a metric, introduces a
technology, or escalates a proficiency. That is sound, but adversarial: it
holds only for the failure modes the validator anticipates.

This package inverts it. The user maintains a corpus of blocks they wrote and
verified, and tailoring selects a subset. The model never authors a claim, so
the worst case is a badly chosen true statement — a ranking bug, not a
credibility failure. The validator still earns its place one layer down, for
the optional rephrasing pass.
"""

from auto_interner.corpus.blocks import Block, BlockKind, Bullet, CorpusError, load_corpus
from auto_interner.corpus.coverage import CoverageReport, build_report
from auto_interner.corpus.render import render_coverage, render_provenance, render_resume
from auto_interner.corpus.requirements import Priority, Requirement, extract_requirements
from auto_interner.corpus.selection import Selection, select
from auto_interner.corpus.tagging import TagHit, explain, tag_text

__all__ = [
    "Block",
    "BlockKind",
    "Bullet",
    "CorpusError",
    "load_corpus",
    "CoverageReport",
    "build_report",
    "Priority",
    "Requirement",
    "extract_requirements",
    "TagHit",
    "tag_text",
    "explain",
    "Selection",
    "select",
    "render_resume",
    "render_coverage",
    "render_provenance",
]
