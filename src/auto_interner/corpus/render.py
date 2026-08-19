"""Render a selection to text, with an auditable provenance trail."""

from __future__ import annotations

from auto_interner.corpus.coverage import CoverageReport
from auto_interner.corpus.selection import Selection

_KIND_HEADING = {
    "experience": "EXPERIENCE",
    "project": "PROJECTS",
    "skill": "SKILLS",
    "education": "EDUCATION",
}


def render_resume(selection: Selection) -> str:
    lines: list[str] = []
    current_kind: str | None = None
    for sel in selection.blocks:
        kind = sel.block.kind.value
        if kind != current_kind:
            if lines:
                lines.append("")
            lines.append(_KIND_HEADING.get(kind, kind.upper()))
            lines.append("-" * len(_KIND_HEADING.get(kind, kind.upper())))
            current_kind = kind
        header = sel.block.title
        if sel.block.org:
            header += f" — {sel.block.org}"
        if sel.block.dates:
            header += f"  ({sel.block.dates})"
        lines.append(header)
        for bullet in sel.bullets:
            lines.append(f"  • {bullet.bullet.text}")
    return "\n".join(lines)


def render_provenance(selection: Selection) -> str:
    """Every line, and the requirement that earned its place."""
    lines = ["PROVENANCE — why each bullet was selected", ""]
    for sel in selection.blocks:
        lines.append(f"[{sel.block.id}] {sel.block.title}")
        for bullet in sel.bullets:
            covers = ", ".join(sorted(bullet.covers)) or "(narrative continuity)"
            preview = bullet.bullet.text[:70] + ("…" if len(bullet.bullet.text) > 70 else "")
            lines.append(f"    covers: {covers}")
            lines.append(f"      text: {preview}")
        lines.append("")
    return "\n".join(lines)


def render_coverage(report: CoverageReport) -> str:
    lines = [f"COVERAGE — {report.score():.0%} of requirement weight surfaced", ""]

    if report.shown:
        lines.append("Surfaced:")
        for status in report.shown:
            where = ", ".join(status.shown_in)
            lines.append(
                f"  [{status.requirement.priority.value:<9}] {status.requirement.term}  <- {where}"
            )
        lines.append("")

    if report.missed:
        lines.append("In your corpus but cut for length (raise --budget to include):")
        for status in report.missed:
            where = ", ".join(status.available_in)
            lines.append(
                f"  [{status.requirement.priority.value:<9}] "
                f"{status.requirement.term}  (in {where})"
            )
        lines.append("")

    if report.gaps:
        lines.append("GAPS — nothing in your corpus supports these:")
        for status in report.gaps:
            lines.append(f"  [{status.requirement.priority.value:<9}] {status.requirement.term}")
            lines.append(f'       posting said: "{status.requirement.evidence[:90]}"')
        lines.append("")
        required = report.required_gaps()
        if required:
            terms = ", ".join(s.requirement.term for s in required)
            lines.append(f"  {len(required)} of these are stated as required: {terms}")
            lines.append("  Add a truthful block if you have the experience. Otherwise this")
            lines.append("  is a real mismatch, and no amount of rewording fixes it.")
    return "\n".join(lines)
