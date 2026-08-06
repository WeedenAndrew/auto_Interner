"""Conservative Tier 0 location classification."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

_US_STATE_ABBREVIATIONS = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
    }
)

_US_STATE_NAMES = frozenset(
    {
        "alabama",
        "alaska",
        "arizona",
        "arkansas",
        "california",
        "colorado",
        "connecticut",
        "delaware",
        "florida",
        "georgia",
        "hawaii",
        "idaho",
        "illinois",
        "indiana",
        "iowa",
        "kansas",
        "kentucky",
        "louisiana",
        "maine",
        "maryland",
        "massachusetts",
        "michigan",
        "minnesota",
        "mississippi",
        "missouri",
        "montana",
        "nebraska",
        "nevada",
        "new hampshire",
        "new jersey",
        "new mexico",
        "new york",
        "north carolina",
        "north dakota",
        "ohio",
        "oklahoma",
        "oregon",
        "pennsylvania",
        "rhode island",
        "south carolina",
        "south dakota",
        "tennessee",
        "texas",
        "utah",
        "vermont",
        "virginia",
        "washington",
        "west virginia",
        "wisconsin",
        "wyoming",
        "district of columbia",
    }
)

_EXACT_US_FORMS = frozenset(
    {"united states", "usa", "remote in usa", "remote in us", "nyc", "la", "sf"}
)
_EXPLICIT_US_PATTERN = re.compile(
    r"\b(?:united\s+states|usa|remote\s+in\s+u\.?s\.?)\b",
    re.IGNORECASE,
)
_NON_US_PATTERN = re.compile(
    r"\b(?:canada|united\s+kingdom|uk|germany|france|india|united\s+arab\s+emirates)\b",
    re.IGNORECASE,
)


class LocationClassification(StrEnum):
    """Confidence class for one structured location string."""

    US = "us"
    NON_US = "non_us"
    UNKNOWN = "unknown"


class LocationScreenStatus(StrEnum):
    """Combined Tier 0 decision across every listed location."""

    PASS = "pass"
    DISQUALIFY = "disqualify"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ClassifiedLocation:
    """One normalized location and its deterministic classification."""

    original: str
    classification: LocationClassification


@dataclass(frozen=True, slots=True)
class LocationScreenResult:
    """Tier 0 result used to decide whether fetching is necessary."""

    status: LocationScreenStatus
    locations: tuple[ClassifiedLocation, ...]


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).strip()


def classify_location(value: str) -> LocationClassification:
    """Classify a location only when a v1 rule is unambiguous."""
    normalized = _normalize(value)
    if not normalized:
        return LocationClassification.UNKNOWN

    lowered = normalized.casefold()
    if lowered in _EXACT_US_FORMS or _EXPLICIT_US_PATTERN.search(normalized):
        return LocationClassification.US

    last_segment = normalized.rsplit(",", maxsplit=1)[-1].strip()
    if last_segment.upper() in _US_STATE_ABBREVIATIONS:
        return LocationClassification.US
    if last_segment.casefold() in _US_STATE_NAMES or lowered in _US_STATE_NAMES:
        return LocationClassification.US

    if _NON_US_PATTERN.search(normalized):
        return LocationClassification.NON_US
    return LocationClassification.UNKNOWN


def screen_locations(locations: tuple[str, ...]) -> LocationScreenResult:
    """Pass any US option, reject only an all-recognized non-US set."""
    classified = tuple(
        ClassifiedLocation(location, classify_location(location)) for location in locations
    )
    if any(item.classification is LocationClassification.US for item in classified):
        return LocationScreenResult(LocationScreenStatus.PASS, classified)
    if classified and all(
        item.classification is LocationClassification.NON_US for item in classified
    ):
        return LocationScreenResult(LocationScreenStatus.DISQUALIFY, classified)
    return LocationScreenResult(LocationScreenStatus.UNKNOWN, classified)
