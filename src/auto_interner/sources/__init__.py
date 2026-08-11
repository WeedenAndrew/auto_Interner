"""Listing snapshot acquisition: one parser, two interchangeable transports.

`snapshot` owns parsing and the shared record types. `git` and `http` are the
transports; neither is imported by the parser, so a transport can be replaced or
added without touching record validation.
"""

from auto_interner.sources.git import (
    GitCommandFailure,
    GitRunner,
    GitSnapshotLoader,
    SubprocessGitRunner,
)
from auto_interner.sources.http import RemoteSnapshotLoader
from auto_interner.sources.snapshot import (
    SnapshotAnomaly,
    SnapshotDownload,
    SnapshotFormatError,
    SnapshotResult,
    SnapshotRetrievalError,
    load_snapshot,
    parse_snapshot_json,
    parse_snapshot_payload,
)

__all__ = [
    "GitCommandFailure",
    "GitRunner",
    "GitSnapshotLoader",
    "RemoteSnapshotLoader",
    "SnapshotAnomaly",
    "SnapshotDownload",
    "SnapshotFormatError",
    "SnapshotResult",
    "SnapshotRetrievalError",
    "SubprocessGitRunner",
    "load_snapshot",
    "parse_snapshot_json",
    "parse_snapshot_payload",
]
