"""F-SRC Phase 1 snapshot parsing cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_interner.source import (
    SnapshotFormatError,
    load_snapshot,
    parse_snapshot_json,
    parse_snapshot_payload,
)

pytestmark = pytest.mark.unit


def _record(listing_id: str = "listing-1", **changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": listing_id,
        "company_name": "Fictional Systems",
        "title": "Software Intern",
        "url": f"https://example.invalid/jobs/{listing_id}",
        "locations": ["Denver, CO"],
        "active": True,
    }
    record.update(changes)
    return record


def test_f_src_001_valid_snapshot_becomes_typed_listings() -> None:
    result = parse_snapshot_payload([_record(source="fixture", date_posted="2026-08-01")])

    assert len(result.listings) == 1
    assert result.listings[0].company_name == "Fictional Systems"
    assert result.listings[0].locations == ("Denver, CO",)
    assert result.listings[0].source == "fixture"
    assert result.anomalies == ()


def test_f_src_002_only_active_records_enter_scanning() -> None:
    result = parse_snapshot_payload([_record(), _record("listing-2", active=False)])

    assert [listing.id for listing in result.active_listings] == ["listing-1"]


def test_f_src_003_missing_id_is_rejected_with_reason() -> None:
    record = _record()
    del record["id"]

    result = parse_snapshot_payload([record])

    assert result.listings == ()
    assert result.anomalies[0].code == "invalid_record"
    assert "id" in result.anomalies[0].detail


def test_listing_id_with_control_character_is_rejected() -> None:
    result = parse_snapshot_payload([_record("listing-1\nlisting-2")])

    assert result.listings == ()
    assert "id" in result.anomalies[0].detail


def test_f_src_004_duplicate_id_is_accepted_once_and_reported() -> None:
    result = parse_snapshot_payload([_record(), _record(title="Different title")])

    assert [listing.id for listing in result.listings] == ["listing-1"]
    assert result.anomalies[0].code == "duplicate_id"
    assert result.anomalies[0].listing_id == "listing-1"


def test_f_src_005_unknown_fields_are_preserved_as_metadata() -> None:
    result = parse_snapshot_payload([_record(future_schema_field={"value": 7})])

    assert result.listings[0].metadata == {"future_schema_field": {"value": 7}}


@pytest.mark.parametrize(
    ("changes", "field_name"),
    [
        ({"title": 42}, "title"),
        ({"locations": "Denver, CO"}, "locations"),
        ({"locations": ["Denver, CO", 42]}, "locations"),
        ({"active": "yes"}, "active"),
    ],
)
def test_f_src_006_wrong_required_type_rejects_record(
    changes: dict[str, object], field_name: str
) -> None:
    record = _record()
    record.update(changes)
    result = parse_snapshot_payload([record])

    assert result.listings == ()
    assert field_name in result.anomalies[0].detail


def test_f_src_007_empty_snapshot_succeeds() -> None:
    assert parse_snapshot_payload([]).listings == ()


def test_f_src_009_invalid_json_raises_without_state_writes(tmp_path: Path) -> None:
    state_marker = tmp_path / "state-marker"
    state_marker.write_text("unchanged", encoding="utf-8")

    with pytest.raises(SnapshotFormatError, match="line 1"):
        parse_snapshot_json("{not-json")

    assert state_marker.read_text(encoding="utf-8") == "unchanged"


def test_snapshot_root_and_record_keys_must_have_expected_shapes() -> None:
    with pytest.raises(SnapshotFormatError, match="JSON array"):
        parse_snapshot_payload({"listings": []})

    result = parse_snapshot_payload(["not-an-object", {1: "not-a-string-key"}])
    assert len(result.anomalies) == 2


def test_load_snapshot_reads_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "listings.json"
    path.write_text(json.dumps([_record(title="Développeur Intern")]), encoding="utf-8")

    assert load_snapshot(path).listings[0].title == "Développeur Intern"
