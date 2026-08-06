"""Build a visually reviewable tailored DOCX using only public fictional data."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from auto_interner.documents.assembler import assemble_resume
from auto_interner.documents.template_reader import read_resume
from auto_interner.models import Listing
from auto_interner.paths import OutputPathPlanner
from auto_interner.rewriting.service import validate_rewrite

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "auto_interner"
    / "demo_data"
    / "fictional_base_resume.docx"
)


def build(data_dir: Path) -> Path:
    resume = read_resume(FIXTURE)
    target_paragraph = next(
        paragraph
        for paragraph in resume.paragraphs_by_id.values()
        if "reduced fictional review time" in paragraph.source_text
    )
    plan = validate_rewrite(
        resume,
        {
            "section_order": [
                "Technical Skills",
                "Experience",
                "Projects",
                "Education",
            ],
            "replacements": [
                {
                    "paragraph_id": target_paragraph.paragraph_id,
                    "replacement": (
                        "Using Python validation tools, reduced fictional review time by 30% "
                        "across 12,000 records."
                    ),
                }
            ],
        },
    )
    listing = Listing(
        id="fictional-listing",
        company_name="Fictional Systems",
        title="Software Engineering Intern",
        url="https://example.invalid/job",
        locations=("Denver, CO",),
        active=True,
    )
    planner = OutputPathPlanner(data_dir, 2027)
    destination = planner.prepare(
        planner.plan(listing, generated_at=datetime(2027, 1, 2, tzinfo=UTC))
    )
    return assemble_resume(resume, plan, destination).output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    arguments = parser.parse_args()
    print(build(arguments.data_dir))


if __name__ == "__main__":
    main()
