"""Strict local snapshot parsing with record-level anomaly reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast

from auto_interner.models import Listing
from auto_interner.network import NetworkFailure, SafeHttpClient

_KNOWN_FIELDS = frozenset(
    {
        "id",
        "company_name",
        "title",
        "url",
        "locations",
        "active",
        "source",
        "date_posted",
        "date_updated",
        "sponsorship",
    }
)


class SnapshotFormatError(ValueError):
    """Raised when the snapshot document itself cannot be interpreted."""


class SnapshotRetrievalError(RuntimeError):
    """Sanitized remote snapshot failure with retry classification."""

    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class SnapshotAnomaly:
    """Sanitized reason one source record was ignored or de-duplicated."""

    index: int
    code: str
    detail: str
    listing_id: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    """Typed listings and non-fatal source anomalies."""

    listings: tuple[Listing, ...]
    anomalies: tuple[SnapshotAnomaly, ...]

    @property
    def active_listings(self) -> tuple[Listing, ...]:
        """Return only records eligible to enter snapshot scanning."""
        return tuple(listing for listing in self.listings if listing.active)


@dataclass(frozen=True, slots=True)
class SnapshotDownload:
    """Validated remote snapshot plus non-sensitive integrity metadata."""

    snapshot: SnapshotResult
    content_hash: str
    content_length: int
    source_version: str | None = None
    changed_since_last_success: bool | None = None


def _required_string(record: dict[str, object], field_name: str) -> str | None:
    value = record.get(field_name)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_string(record: dict[str, object], field_name: str) -> str | None:
    value = record.get(field_name)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _is_safe_listing_id(value: str) -> bool:
    return len(value) <= 500 and not any(
        ord(character) < 32 or ord(character) == 127 for character in value
    )


def _string_keyed_record(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw_record = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw_record):
        return None
    return {cast(str, key): item for key, item in raw_record.items()}


def _parse_listing(
    record: dict[str, object], index: int
) -> tuple[Listing | None, SnapshotAnomaly | None]:
    listing_id = _required_string(record, "id")
    if listing_id is not None and not _is_safe_listing_id(listing_id):
        listing_id = None
    required_strings = {
        "company_name": _required_string(record, "company_name"),
        "title": _required_string(record, "title"),
        "url": _required_string(record, "url"),
    }
    invalid_fields = [name for name, value in required_strings.items() if value is None]
    if listing_id is None:
        invalid_fields.insert(0, "id")

    locations_value = record.get("locations")
    locations: tuple[str, ...] | None = None
    if isinstance(locations_value, list):
        raw_locations = cast(list[object], locations_value)
        if all(isinstance(item, str) for item in raw_locations):
            locations = tuple(
                cast(str, item).strip() for item in raw_locations if cast(str, item).strip()
            )
    if locations is None:
        invalid_fields.append("locations")

    active = record.get("active")
    if not isinstance(active, bool):
        invalid_fields.append("active")

    if invalid_fields:
        fields = ", ".join(dict.fromkeys(invalid_fields))
        return None, SnapshotAnomaly(
            index=index,
            code="invalid_record",
            detail=f"missing or invalid required fields: {fields}",
            listing_id=listing_id,
        )

    metadata = {key: value for key, value in record.items() if key not in _KNOWN_FIELDS}
    return (
        Listing(
            id=cast(str, listing_id),
            company_name=cast(str, required_strings["company_name"]),
            title=cast(str, required_strings["title"]),
            url=cast(str, required_strings["url"]),
            locations=cast(tuple[str, ...], locations),
            active=cast(bool, active),
            source=_optional_string(record, "source"),
            date_posted=_optional_string(record, "date_posted"),
            date_updated=_optional_string(record, "date_updated"),
            sponsorship=_optional_string(record, "sponsorship"),
            metadata=metadata,
        ),
        None,
    )


def parse_snapshot_payload(payload: object) -> SnapshotResult:
    """Convert a decoded JSON array into typed listings without source I/O."""
    if not isinstance(payload, list):
        raise SnapshotFormatError("listing snapshot must be a JSON array")

    listings: list[Listing] = []
    anomalies: list[SnapshotAnomaly] = []
    accepted_ids: set[str] = set()

    for index, value in enumerate(cast(list[object], payload)):
        record = _string_keyed_record(value)
        if record is None:
            anomalies.append(
                SnapshotAnomaly(
                    index=index,
                    code="invalid_record",
                    detail="record must be an object with string field names",
                )
            )
            continue

        listing, anomaly = _parse_listing(record, index)
        if anomaly is not None:
            anomalies.append(anomaly)
            continue
        if listing is None:  # pragma: no cover - paired return invariant
            raise AssertionError("listing parser returned no result")
        if listing.id in accepted_ids:
            anomalies.append(
                SnapshotAnomaly(
                    index=index,
                    code="duplicate_id",
                    detail="duplicate listing ID ignored",
                    listing_id=listing.id,
                )
            )
            continue
        accepted_ids.add(listing.id)
        listings.append(listing)

    return SnapshotResult(tuple(listings), tuple(anomalies))


def parse_snapshot_json(document: str) -> SnapshotResult:
    """Parse a snapshot JSON document with a readable format error."""
    try:
        payload = cast(object, json.loads(document))
    except json.JSONDecodeError as exc:
        raise SnapshotFormatError(f"listing snapshot is invalid JSON at line {exc.lineno}") from exc
    return parse_snapshot_payload(payload)


def load_snapshot(path: Path) -> SnapshotResult:
    """Read and parse one local fixture or previously downloaded snapshot."""
    return parse_snapshot_json(path.read_text(encoding="utf-8"))


class RemoteSnapshotLoader:
    """Download and parse a bounded snapshot through the shared safe HTTP client."""

    _ALLOWED_MEDIA_TYPES = frozenset(
        {"application/json", "application/octet-stream", "text/json", "text/plain"}
    )

    def __init__(self, client: SafeHttpClient) -> None:
        self._client = client

    def download(self, url: str) -> SnapshotDownload:
        """Return a typed snapshot or a sanitized classified failure."""
        try:
            response = self._client.get(url)
        except NetworkFailure as exc:
            raise SnapshotRetrievalError(exc.reason, retryable=exc.retryable) from exc

        raw_content_type = response.header("content-type") or ""
        media_type = raw_content_type.partition(";")[0].strip().casefold()
        if media_type and media_type not in self._ALLOWED_MEDIA_TYPES:
            raise SnapshotRetrievalError(
                "snapshot response is not a supported JSON media type",
                retryable=False,
            )
        try:
            document = response.body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SnapshotRetrievalError(
                "snapshot response is not valid UTF-8",
                retryable=False,
            ) from exc
        try:
            snapshot = parse_snapshot_json(document)
        except SnapshotFormatError as exc:
            raise SnapshotRetrievalError(str(exc), retryable=False) from exc
        return SnapshotDownload(
            snapshot=snapshot,
            content_hash=sha256(response.body).hexdigest(),
            content_length=len(response.body),
        )
