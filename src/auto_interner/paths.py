"""Portable, contained output-path planning for generated resumes."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path

from auto_interner.models import Listing

_MAX_COMPONENT_CHARACTERS = 80
_MAX_COMPONENT_BYTES = 180
_DIGEST_LENGTH = 10
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
_NOISE_TOKENS = frozenset(
    {
        "intern",
        "internship",
        "coop",
        "trainee",
        "spring",
        "summer",
        "fall",
        "autumn",
        "winter",
    }
)
_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_COOP_PATTERN = re.compile(r"\bco[\W_]*op\b", re.IGNORECASE)
_YEAR_PATTERN = re.compile(r"[0-9]{4}\Z")


class OutputPathError(ValueError):
    """Raised when an output plan is malformed or leaves its configured root."""


class OutputCollisionError(FileExistsError):
    """Raised when a generated-resume path already exists."""


def _require_aware(timestamp: datetime) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generation timestamp must include an explicit timezone")


def normalize_role(title: str) -> str:
    """Return an order-invariant v1 role key without stemming domain terms."""
    normalized = unicodedata.normalize("NFKC", title).casefold()
    normalized = _COOP_PATTERN.sub(" coop ", normalized)
    tokens = {
        token
        for token in _TOKEN_PATTERN.findall(normalized)
        if token not in _NOISE_TOKENS and not _YEAR_PATTERN.fullmatch(token)
    }
    return " ".join(sorted(tokens))


def _bounded_component(component: str, *, uniqueness_source: str) -> str:
    encoded = component.encode("utf-8")
    if len(component) <= _MAX_COMPONENT_CHARACTERS and len(encoded) <= _MAX_COMPONENT_BYTES:
        return component

    digest = sha256(uniqueness_source.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]
    suffix = f"-{digest}"
    maximum_prefix_characters = _MAX_COMPONENT_CHARACTERS - len(suffix)
    maximum_prefix_bytes = _MAX_COMPONENT_BYTES - len(suffix.encode("ascii"))
    prefix: list[str] = []
    prefix_bytes = 0
    for character in component:
        encoded_character = character.encode("utf-8")
        if len(prefix) >= maximum_prefix_characters:
            break
        if prefix_bytes + len(encoded_character) > maximum_prefix_bytes:
            break
        prefix.append(character)
        prefix_bytes += len(encoded_character)
    bounded_prefix = "".join(prefix).rstrip("-.")
    return f"{bounded_prefix}{suffix}"


def safe_path_component(value: str, *, fallback_prefix: str, listing_id: str) -> str:
    """Create a stable lowercase component safe on Windows, Linux, and macOS."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    characters = [character if character.isalnum() else "-" for character in normalized]
    component = re.sub(r"-+", "-", "".join(characters)).strip("-. ")
    if not component:
        fallback_digest = sha256(listing_id.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]
        normalized_fallback = unicodedata.normalize("NFKC", fallback_prefix).casefold()
        fallback_characters = [
            character if character.isalnum() else "-" for character in normalized_fallback
        ]
        safe_fallback = re.sub(r"-+", "-", "".join(fallback_characters)).strip("-") or "item"
        component = f"{safe_fallback}-{fallback_digest}"
    if component.upper() in _WINDOWS_RESERVED_NAMES:
        component = f"item-{component}"
    return _bounded_component(component, uniqueness_source=normalized or listing_id)


@dataclass(frozen=True, slots=True)
class OutputPathPlan:
    """A write-free, validated destination for one generated resume."""

    cycle_dir: Path
    company_dir: Path
    output_path: Path
    company_component: str
    role_component: str
    generated_on: date


class OutputPathPlanner:
    """Plan safe cycle-scoped paths and create them only on explicit preparation."""

    def __init__(self, data_dir: Path, recruiting_year: int) -> None:
        if not 2000 <= recruiting_year <= 2100:
            raise ValueError("recruiting year must be between 2000 and 2100")
        self.data_dir = data_dir
        self.recruiting_year = recruiting_year
        self.cycle_dir = data_dir / str(recruiting_year)

    @staticmethod
    def company_component(listing: Listing) -> str:
        """Return the stable directory component for a listing company."""
        return safe_path_component(
            listing.company_name,
            fallback_prefix="company",
            listing_id=listing.id,
        )

    @staticmethod
    def role_component(listing: Listing) -> str:
        """Return the stable filename component for a normalized listing role."""
        role_key = normalize_role(listing.title)
        return safe_path_component(
            role_key,
            fallback_prefix="role",
            listing_id=listing.id,
        )

    def _assert_contained(self, path: Path) -> None:
        root = self.data_dir.resolve(strict=False)
        try:
            path.resolve(strict=False).relative_to(root)
        except (OSError, ValueError) as exc:
            raise OutputPathError("planned output must remain inside DATA_DIR") from exc

    def plan(self, listing: Listing, *, generated_at: datetime) -> OutputPathPlan:
        """Return a contained output plan without creating any directories."""
        _require_aware(generated_at)
        generated_on = generated_at.date()
        company_component = self.company_component(listing)
        role_component = self.role_component(listing)
        company_dir = self.cycle_dir / company_component
        output_path = company_dir / f"{role_component}_{generated_on:%m-%d-%y}.docx"
        self._assert_contained(company_dir)
        self._assert_contained(output_path)
        return OutputPathPlan(
            cycle_dir=self.cycle_dir,
            company_dir=company_dir,
            output_path=output_path,
            company_component=company_component,
            role_component=role_component,
            generated_on=generated_on,
        )

    def prepare(self, plan: OutputPathPlan) -> Path:
        """Lazily create the company directory and refuse an existing filename."""
        expected_output_name = f"{plan.role_component}_{plan.generated_on:%m-%d-%y}.docx"
        if (
            plan.cycle_dir != self.cycle_dir
            or plan.company_dir.parent != self.cycle_dir
            or plan.company_dir.name != plan.company_component
            or plan.output_path.parent != plan.company_dir
            or plan.output_path.name != expected_output_name
        ):
            raise OutputPathError("output plan does not belong to this planner")
        if plan.company_dir.is_symlink():
            raise OutputPathError("company output directory must not be a symbolic link")
        self._assert_contained(plan.company_dir)
        self._assert_contained(plan.output_path)
        plan.company_dir.mkdir(parents=True, exist_ok=True)
        self._assert_contained(plan.company_dir)
        self._assert_contained(plan.output_path)
        if plan.output_path.exists() or plan.output_path.is_symlink():
            raise OutputCollisionError("generated resume already exists; refusing to overwrite it")
        return plan.output_path
