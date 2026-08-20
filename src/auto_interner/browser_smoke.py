"""Offline Chromium/chromedriver compatibility smoke check for the target image."""

from __future__ import annotations

import os
import sys
import traceback
from contextlib import suppress
from pathlib import Path

from auto_interner.fetcher import SeleniumChromeFactory

_TOKEN = "auto-interner-browser-smoke"


def _enabled(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _report(message: str) -> None:
    """Write one diagnostic line to stderr.

    This gate previously returned a bare exit code and printed nothing, so a CI
    failure said only that Chromium did not start. The cause turned out to be a
    read-only ``$HOME``, which the environment lines below now make obvious
    without needing a local reproduction.
    """
    print(f"browser-smoke: {message}", file=sys.stderr)


def _home_is_writable() -> bool:
    home = Path(os.environ.get("HOME", ""))
    if not home.is_dir():
        return False
    probe = home / ".browser-smoke-probe"
    try:
        probe.touch()
    except OSError:
        return False
    with suppress(OSError):
        probe.unlink()
    return True


def main() -> int:
    """Open an in-memory page and always close the browser process."""
    binary = Path(os.environ.get("CHROMIUM_BINARY", "/usr/bin/chromium"))
    driver = Path(os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver"))
    for label, path in (("CHROMIUM_BINARY", binary), ("CHROMEDRIVER_PATH", driver)):
        if not path.is_file():
            _report(f"{label} is not an existing file: {path}")
            return 1

    # Chromium needs $HOME writable twice: once for its profile, and again for
    # the Crashpad database, whose path it derives from $HOME regardless of
    # --user-data-dir. Reporting this up front turns the most likely container
    # failure into one readable line instead of a silent abort.
    _report(f"chromium={binary} chromedriver={driver}")
    _report(f"HOME={os.environ.get('HOME', '<unset>')} writable={_home_is_writable()}")

    session = None
    try:
        session = SeleniumChromeFactory(
            chromium_binary=binary,
            chromedriver_path=driver,
            no_sandbox=_enabled(os.environ.get("BROWSER_NO_SANDBOX", "false")),
        ).create()
        session.set_page_load_timeout(30)
        session.set_script_timeout(30)
        session.get(f"data:text/html,<title>{_TOKEN}</title><p>{_TOKEN}</p>")
        if _TOKEN in session.page_source:
            _report("page rendered, browser is usable")
            return 0
        _report("browser started but the page did not contain the expected token")
        return 1
    except Exception:
        _report("browser session failed, traceback follows")
        traceback.print_exc()
        return 1
    finally:
        if session is not None:
            with suppress(Exception):
                session.quit()


if __name__ == "__main__":  # pragma: no cover - exercised by the arm64 image
    raise SystemExit(main())
