"""The bounded rewrite/grade loop, its budget, and its feedback discipline."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from auto_interner.demo import fictional_base_resume_path
from auto_interner.documents.template_reader import ResumeDocument, read_resume
from auto_interner.rewriting.grading import GRADE_TOOL_NAME, GradeResponseError, parse_grade
from auto_interner.rewriting.loop import request_graded_rewrite
from auto_interner.rewriting.service import REWRITE_TOOL_NAME, UnsupportedRewriteError

pytestmark = [pytest.mark.unit]

POSTING = "A fictional posting seeking Python services work and automated testing."


@pytest.fixture(name="resume")
def _resume() -> ResumeDocument:
    return read_resume(fictional_base_resume_path())


class ScriptedModel:
    """Returns a queued response per tool and records what it was told."""

    def __init__(
        self,
        *,
        rewrites: list[object],
        grades: list[object],
    ) -> None:
        self._rewrites = list(rewrites)
        self._grades = list(grades)
        self.calls: list[str] = []
        self.rewrite_prompts: list[dict[str, object]] = []

    def call_tool(
        self,
        *,
        tool_name: str,
        input_schema: Mapping[str, object],
        system_prompt: str,
        user_prompt: str,
    ) -> object:
        del input_schema, system_prompt
        self.calls.append(tool_name)
        if tool_name == GRADE_TOOL_NAME:
            return self._grades.pop(0)
        self.rewrite_prompts.append(json.loads(user_prompt))
        return self._rewrites.pop(0)


def _reorder(resume: ResumeDocument) -> dict[str, object]:
    return {"section_order": list(resume.section_names), "replacements": []}


def _invents_a_technology(resume: ResumeDocument) -> dict[str, object]:
    target = next(
        paragraph.paragraph_id
        for paragraph in resume.paragraphs_by_id.values()
        if paragraph.rewritable and "fictional data pipeline" in paragraph.source_text
    )
    return {
        "section_order": list(resume.section_names),
        "replacements": [
            {"paragraph_id": target, "replacement": "Wrote Kubernetes checks for 4 teammates."}
        ],
    }


def _grade(*, aligned: bool, confidence: str = "high") -> dict[str, object]:
    return {"aligned": aligned, "confidence": confidence, "concern": "a fictional concern"}


def test_a_clean_first_attempt_costs_one_rewrite_and_one_grade(resume: ResumeDocument) -> None:
    model = ScriptedModel(rewrites=[_reorder(resume)], grades=[_grade(aligned=True)])

    result = request_graded_rewrite(model, resume, POSTING)

    assert result.attempts == 1
    assert result.rejected == ()
    assert model.calls == [REWRITE_TOOL_NAME, GRADE_TOOL_NAME]


def test_a_validator_rejection_is_retried_once(resume: ResumeDocument) -> None:
    model = ScriptedModel(
        rewrites=[_invents_a_technology(resume), _reorder(resume)],
        grades=[_grade(aligned=True)],
    )

    result = request_graded_rewrite(model, resume, POSTING)

    assert result.attempts == 2
    assert [item.gate for item in result.rejected] == ["validator"]
    # The failed attempt never reached the grader.
    assert model.calls == [REWRITE_TOOL_NAME, REWRITE_TOOL_NAME, GRADE_TOOL_NAME]


def test_a_grader_rejection_is_retried_once(resume: ResumeDocument) -> None:
    model = ScriptedModel(
        rewrites=[_reorder(resume), _reorder(resume)],
        grades=[_grade(aligned=False), _grade(aligned=True)],
    )

    result = request_graded_rewrite(model, resume, POSTING)

    assert result.attempts == 2
    assert [item.gate for item in result.rejected] == ["grader"]


def test_the_budget_is_shared_across_both_gates(resume: ResumeDocument) -> None:
    """One validator failure then one grader failure exhausts it, not four."""
    model = ScriptedModel(
        rewrites=[_invents_a_technology(resume), _reorder(resume)],
        grades=[_grade(aligned=False)],
    )

    with pytest.raises(UnsupportedRewriteError, match="every one of 2 attempts"):
        request_graded_rewrite(model, resume, POSTING)

    assert model.calls.count(REWRITE_TOOL_NAME) == 2


def test_low_confidence_misalignment_never_blocks(resume: ResumeDocument) -> None:
    """Mirrors the Tier 2 policy: an uncertain judgement is not evidence."""
    model = ScriptedModel(
        rewrites=[_reorder(resume)],
        grades=[_grade(aligned=False, confidence="low")],
    )

    result = request_graded_rewrite(model, resume, POSTING)

    assert result.attempts == 1


def test_feedback_names_a_category_and_never_the_offending_text(
    resume: ResumeDocument,
) -> None:
    """The safety property. A model told which token tripped the check learns to
    dodge the check rather than to be accurate."""
    model = ScriptedModel(
        rewrites=[_invents_a_technology(resume), _reorder(resume)],
        grades=[_grade(aligned=True)],
    )

    request_graded_rewrite(model, resume, POSTING)

    retry_prompt = model.rewrite_prompts[1]
    feedback = retry_prompt["previous_attempt_rejected_because"]
    assert isinstance(feedback, str)
    assert "technology" in feedback
    assert "Kubernetes" not in feedback
    assert "Kubernetes" not in json.dumps(retry_prompt)


def test_the_first_attempt_carries_no_feedback(resume: ResumeDocument) -> None:
    model = ScriptedModel(rewrites=[_reorder(resume)], grades=[_grade(aligned=True)])

    request_graded_rewrite(model, resume, POSTING)

    assert "previous_attempt_rejected_because" not in model.rewrite_prompts[0]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"aligned": True, "confidence": "high"},
        {"aligned": "yes", "confidence": "high", "concern": "c"},
        {"aligned": True, "confidence": "certain", "concern": "c"},
        {"aligned": True, "confidence": "high", "concern": "x" * 301},
        {"aligned": True, "confidence": "high", "concern": "c", "extra": 1},
    ],
)
def test_a_malformed_grade_is_rejected(payload: object) -> None:
    with pytest.raises(GradeResponseError):
        parse_grade(payload)


def test_the_grader_is_not_shown_the_rewriters_reasoning(resume: ResumeDocument) -> None:
    """A grader shown why the rewriter believes its work is good agrees with it."""
    captured: list[str] = []

    class Capturing(ScriptedModel):
        def call_tool(self, **kwargs: object) -> object:
            if kwargs["tool_name"] == GRADE_TOOL_NAME:
                captured.append(str(kwargs["user_prompt"]))
            return super().call_tool(**kwargs)  # type: ignore[arg-type]

    model = Capturing(
        rewrites=[_invents_a_technology(resume), _reorder(resume)],
        grades=[_grade(aligned=True)],
    )
    request_graded_rewrite(model, resume, POSTING)

    assert captured and "previous_attempt_rejected_because" not in captured[0]


def test_max_attempts_must_be_positive(resume: ResumeDocument, tmp_path: Path) -> None:
    del tmp_path
    model = ScriptedModel(rewrites=[], grades=[])
    with pytest.raises(ValueError, match="must be positive"):
        request_graded_rewrite(model, resume, POSTING, max_attempts=0)
