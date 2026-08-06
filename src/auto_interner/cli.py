"""Command-line entry points for diagnostics and the offline demonstration."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

from auto_interner import __version__
from auto_interner.composition import build_fixture_coordinator, build_live_coordinator
from auto_interner.config import Settings, SettingsError
from auto_interner.demo import DemoDataError, run_demo
from auto_interner.git_source import GitSnapshotLoader
from auto_interner.logging_config import configure_logging
from auto_interner.network import SafeHttpClient
from auto_interner.run_lock import RunAlreadyActiveError
from auto_interner.runtime import run_daemon
from auto_interner.source import (
    RemoteSnapshotLoader,
    SnapshotFormatError,
    SnapshotRetrievalError,
)
from auto_interner.state_store import StateCorruptionError, StateStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto-interner",
        description="Validate configuration or run the offline screening demo.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    config_parser = subparsers.add_parser(
        "config-check",
        help="validate settings and local runtime prerequisites",
    )
    config_parser.add_argument(
        "--require-model-key",
        action="store_true",
        help="also require ANTHROPIC_API_KEY for a later live-model run",
    )
    demo_parser = subparsers.add_parser(
        "demo",
        help="process bundled fictional fixtures without external calls",
    )
    demo_parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("runtime/demo-state"),
        help="directory for demonstration decisions and retry state",
    )
    demo_parser.add_argument(
        "--max-fetch-attempts",
        type=int,
        default=3,
        help="failures before an item enters manual review (default: 3)",
    )
    subparsers.add_parser(
        "source-check",
        help="download and validate the configured listing snapshot",
    )
    run_parser = subparsers.add_parser(
        "run-once",
        help="run the complete pipeline once (shadow mode remains the live default)",
    )
    run_parser.add_argument(
        "--fixture",
        action="store_true",
        help="use only bundled fictional data and a deterministic model fake",
    )
    run_parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("runtime/fixture-data"),
        help="fixture output root (used only with --fixture)",
    )
    run_parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("runtime/fixture-state"),
        help="fixture state root (used only with --fixture)",
    )
    run_parser.add_argument(
        "--write",
        action="store_true",
        help="publish the fictional DOCX; fixture runs otherwise use shadow mode",
    )
    daemon_parser = subparsers.add_parser(
        "daemon",
        help="run immediately and poll again only after the prior run finishes",
    )
    daemon_parser.add_argument(
        "--interval-seconds",
        type=float,
        help="override the configured poll interval",
    )
    review_parser = subparsers.add_parser(
        "manual-review-count",
        help="print the number of unique listings awaiting manual review",
    )
    review_parser.add_argument(
        "--state-dir",
        type=Path,
        help="state root; defaults to STATE_DIR or runtime/state",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run the diagnostic CLI and return a process exit code."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0

    if arguments.command == "demo":
        try:
            result, snapshot, fetcher = run_demo(
                arguments.state_dir,
                max_fetch_attempts=arguments.max_fetch_attempts,
            )
        except (
            DemoDataError,
            SnapshotFormatError,
            StateCorruptionError,
            OSError,
            ValueError,
        ) as exc:
            print(f"Demo error: {exc}", file=sys.stderr)
            return 2
        summary = result.as_dict()
        summary["source_anomalies"] = len(snapshot.anomalies)
        summary["fixture_fetches"] = len(fetcher.calls)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if arguments.command == "source-check":
        try:
            settings = Settings.from_env(environment)
            configure_logging(settings.log_level)
            if settings.listings_source_mode == "git":
                download = GitSnapshotLoader(
                    repository_url=settings.source_repository_url,
                    branch_ref=settings.listings_git_ref,
                    snapshot_path=settings.listings_git_path,
                    cache_dir=settings.source_cache_dir,
                    timeout_seconds=settings.git_fetch_timeout_seconds,
                ).download()
            else:
                client = SafeHttpClient(
                    timeout_seconds=settings.static_fetch_timeout_seconds,
                    max_response_bytes=20 * 1024 * 1024,
                )
                download = RemoteSnapshotLoader(client).download(settings.source_url)
        except (SettingsError, SnapshotRetrievalError, OSError, ValueError) as exc:
            print(f"Source error: {exc}", file=sys.stderr)
            return 2
        source_summary: dict[str, object] = {
            "accepted_records": len(download.snapshot.listings),
            "active_records": len(download.snapshot.active_listings),
            "anomalies": len(download.snapshot.anomalies),
            "content_hash": download.content_hash,
            "content_length": download.content_length,
            "source_mode": settings.listings_source_mode,
        }
        if download.source_version is not None:
            source_summary["source_version"] = download.source_version
        if download.changed_since_last_success is not None:
            source_summary["changed_since_last_success"] = download.changed_since_last_success
        print(json.dumps(source_summary, indent=2, sort_keys=True))
        return 0

    if arguments.command == "manual-review-count":
        values = os.environ if environment is None else environment
        state_dir = arguments.state_dir or Path(values.get("STATE_DIR", "runtime/state"))
        try:
            count = StateStore(state_dir).manual_review_count()
        except (StateCorruptionError, OSError) as exc:
            print(f"State error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"manual_review_count": count}, indent=2, sort_keys=True))
        return 0

    if arguments.command == "run-once":
        try:
            if arguments.fixture:
                coordinator = build_fixture_coordinator(
                    data_dir=arguments.data_dir,
                    state_dir=arguments.state_dir,
                    write=bool(arguments.write),
                )
            else:
                if arguments.write:
                    raise SettingsError("--write is only accepted with --fixture; use SHADOW_MODE")
                settings = Settings.from_env(environment)
                configure_logging(settings.log_level)
                coordinator = build_live_coordinator(settings)
            run_summary = coordinator.run_once()
        except (
            SettingsError,
            SnapshotRetrievalError,
            StateCorruptionError,
            RunAlreadyActiveError,
            OSError,
            ValueError,
        ) as exc:
            print(f"Run error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(run_summary.as_dict(), indent=2, sort_keys=True))
        return 0

    if arguments.command == "daemon":
        try:
            settings = Settings.from_env(environment)
            configure_logging(settings.log_level)
            coordinator = build_live_coordinator(settings)
            interval_seconds = (
                settings.poll_interval_hours * 60 * 60
                if arguments.interval_seconds is None
                else arguments.interval_seconds
            )
            run_daemon(
                coordinator,
                interval_seconds=interval_seconds,
                stop_event=threading.Event(),
            )
        except KeyboardInterrupt:
            return 0
        except (SettingsError, StateCorruptionError, OSError, ValueError) as exc:
            print(f"Daemon error: {exc}", file=sys.stderr)
            return 2
        return 0

    try:
        settings = Settings.from_env(environment)
        configure_logging(settings.log_level)
        settings.validate_runtime_requirements(
            require_model_key=bool(arguments.require_model_key),
            require_base_resume=True,
        )
    except SettingsError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(settings.safe_summary(), indent=2, sort_keys=True))
    return 0
