"""Protected HTTP snapshot transport built on the shared safe client."""

from __future__ import annotations

from hashlib import sha256

from auto_interner.network import NetworkFailure, SafeHttpClient
from auto_interner.sources.snapshot import (
    SnapshotDownload,
    SnapshotFormatError,
    SnapshotRetrievalError,
    parse_snapshot_json,
)


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
