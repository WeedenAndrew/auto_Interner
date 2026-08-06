"""Cycle-scoped company and normalized-role deduplication."""

from __future__ import annotations

import logging
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from auto_interner.models import Listing
from auto_interner.paths import OutputPathPlanner, normalize_role

LOGGER = logging.getLogger(__name__)

_GENERATED_FILENAME_PATTERN = re.compile(
    r"(?P<role>.+)_(?P<month>[0-9]{2})-(?P<day>[0-9]{2})-(?P<year>[0-9]{2})\.docx\Z",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DedupeAnomaly:
    """A safe reason one generated-document entry was ignored."""

    filename: str
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class DedupeResult:
    """Duplicate decision and non-fatal anomalies from one company directory."""

    is_duplicate: bool
    normalized_role: str
    cutoff_date: date
    matched_path: Path | None
    matched_generated_on: date | None
    anomalies: tuple[DedupeAnomaly, ...]


def six_calendar_month_cutoff(as_of: date) -> date:
    """Subtract six calendar months, clamping to the target month's final day."""
    zero_based_month = as_of.month - 1 - 6
    year = as_of.year + zero_based_month // 12
    month = zero_based_month % 12 + 1
    day = min(as_of.day, monthrange(year, month)[1])
    return date(year, month, day)


def _safe_filename(filename: str) -> str:
    return " ".join(filename.split())[:200] or "unnamed entry"


def _anomaly(path: Path, code: str, detail: str) -> DedupeAnomaly:
    filename = _safe_filename(path.name)
    LOGGER.warning(
        "Ignored generated-resume entry during deduplication",
        extra={"event": "dedupe_anomaly", "generated_filename": filename, "reason": code},
    )
    return DedupeAnomaly(filename=filename, code=code, detail=detail)


def _resolve_two_digit_year(two_digit_year: int, as_of_year: int) -> int:
    century = as_of_year // 100 * 100
    candidates = (
        century - 100 + two_digit_year,
        century + two_digit_year,
        century + 100 + two_digit_year,
    )
    return min(candidates, key=lambda candidate: abs(candidate - as_of_year))


def _parse_generated_filename(path: Path, as_of: date) -> tuple[str, str, date] | DedupeAnomaly:
    if path.is_symlink() or not path.is_file():
        return _anomaly(path, "unsafe_entry", "entry is not a regular generated-resume file")
    match = _GENERATED_FILENAME_PATTERN.fullmatch(path.name)
    if match is None:
        return _anomaly(path, "malformed_filename", "filename does not match the generated format")
    role_component = match.group("role")
    role_key = normalize_role(role_component)
    if not role_key:
        return _anomaly(path, "missing_role", "filename contains no comparable role terms")
    year = _resolve_two_digit_year(int(match.group("year")), as_of.year)
    try:
        generated_on = date(year, int(match.group("month")), int(match.group("day")))
    except ValueError:
        return _anomaly(path, "invalid_date", "filename contains an invalid generation date")
    if generated_on > as_of:
        return _anomaly(path, "future_date", "filename generation date is in the future")
    return role_component, role_key, generated_on


class RoleDeduplicator:
    """Compare one listing only with generated resumes in its current company/cycle."""

    def __init__(self, data_dir: Path, recruiting_year: int) -> None:
        self._planner = OutputPathPlanner(data_dir, recruiting_year)

    def check(self, listing: Listing, *, as_of: datetime) -> DedupeResult:
        """Return a conservative duplicate result without creating or changing files."""
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("dedupe timestamp must include an explicit timezone")
        as_of_date = as_of.date()
        cutoff = six_calendar_month_cutoff(as_of_date)
        target_role = normalize_role(listing.title)
        if not target_role:
            return DedupeResult(False, target_role, cutoff, None, None, ())
        target_component = self._planner.role_component(listing)

        company_dir = self._planner.cycle_dir / self._planner.company_component(listing)
        if not company_dir.exists():
            return DedupeResult(False, target_role, cutoff, None, None, ())
        if company_dir.is_symlink() or not company_dir.is_dir():
            anomaly = _anomaly(
                company_dir,
                "unsafe_company_directory",
                "company path is not a regular directory",
            )
            return DedupeResult(False, target_role, cutoff, None, None, (anomaly,))

        anomalies: list[DedupeAnomaly] = []
        matches: list[tuple[date, Path]] = []
        try:
            entries = sorted(company_dir.iterdir(), key=lambda path: path.name.casefold())
        except OSError as exc:
            raise OSError("company output directory could not be scanned") from exc

        for path in entries:
            if path.suffix.casefold() != ".docx":
                continue
            parsed = _parse_generated_filename(path, as_of_date)
            if isinstance(parsed, DedupeAnomaly):
                anomalies.append(parsed)
                continue
            candidate_component, candidate_role, generated_on = parsed
            roles_match = candidate_role == target_role or (
                candidate_component.casefold() == target_component.casefold()
            )
            if roles_match and generated_on > cutoff:
                matches.append((generated_on, path))

        if not matches:
            return DedupeResult(False, target_role, cutoff, None, None, tuple(anomalies))
        matched_generated_on, matched_path = max(matches, key=lambda item: item[0])
        return DedupeResult(
            True,
            target_role,
            cutoff,
            matched_path,
            matched_generated_on,
            tuple(anomalies),
        )
