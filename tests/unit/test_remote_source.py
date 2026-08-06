"""Remote snapshot download, media, decoding, and failure-classification cases."""

from __future__ import annotations

import json
from typing import cast

import pytest

from auto_interner.network import HttpResponse, NetworkFailure, SafeHttpClient
from auto_interner.source import RemoteSnapshotLoader, SnapshotRetrievalError

pytestmark = [pytest.mark.unit, pytest.mark.contract]


class FakeClient:
    def __init__(self, response: HttpResponse | NetworkFailure) -> None:
        self.response = response
        self.calls: list[str] = []

    def get(self, url: str) -> HttpResponse:
        self.calls.append(url)
        if isinstance(self.response, NetworkFailure):
            raise self.response
        return self.response


def _record() -> dict[str, object]:
    return {
        "id": "fixture-one",
        "company_name": "Fictional Systems",
        "title": "Software Intern",
        "url": "https://example.invalid/jobs/fixture-one",
        "locations": ["Denver, CO"],
        "active": True,
    }


def _loader(response: HttpResponse | NetworkFailure) -> tuple[RemoteSnapshotLoader, FakeClient]:
    client = FakeClient(response)
    return RemoteSnapshotLoader(cast(SafeHttpClient, client)), client


def test_remote_snapshot_download_returns_typed_records_and_integrity_metadata() -> None:
    body = json.dumps([_record()]).encode()
    response = HttpResponse(
        "https://source.example/listings.json",
        200,
        {"content-type": "application/json; charset=utf-8"},
        body,
    )
    loader, client = _loader(response)

    download = loader.download("https://source.example/listings.json")

    assert download.snapshot.listings[0].id == "fixture-one"
    assert download.content_length == len(body)
    assert len(download.content_hash) == 64
    assert client.calls == ["https://source.example/listings.json"]


def test_raw_text_media_type_and_utf8_bom_are_supported() -> None:
    body = b"\xef\xbb\xbf" + json.dumps([_record()]).encode()
    response = HttpResponse(
        "https://source.example/listings.json",
        200,
        {"content-type": "text/plain"},
        body,
    )
    loader, _ = _loader(response)

    assert len(loader.download("https://source.example/listings.json").snapshot.listings) == 1


def test_f_src_008_network_error_remains_retryable() -> None:
    loader, _ = _loader(NetworkFailure("request timed out", retryable=True))

    with pytest.raises(SnapshotRetrievalError, match="timed out") as captured:
        loader.download("https://source.example/listings.json")

    assert captured.value.retryable is True


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (
            HttpResponse(
                "https://source.example/value",
                200,
                {"content-type": "text/html"},
                b"<html></html>",
            ),
            "media type",
        ),
        (
            HttpResponse(
                "https://source.example/value",
                200,
                {"content-type": "application/json"},
                b"\xff",
            ),
            "UTF-8",
        ),
        (
            HttpResponse(
                "https://source.example/value",
                200,
                {"content-type": "application/json"},
                b"{invalid",
            ),
            "invalid JSON",
        ),
    ],
)
def test_invalid_remote_snapshot_fails_permanently(response: HttpResponse, reason: str) -> None:
    loader, _ = _loader(response)

    with pytest.raises(SnapshotRetrievalError, match=reason) as captured:
        loader.download("https://source.example/value")

    assert captured.value.retryable is False
