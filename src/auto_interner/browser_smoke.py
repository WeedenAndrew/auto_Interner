"""Offline Chromium/chromedriver compatibility smoke check for the target image."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

from auto_interner.fetcher import SeleniumChromeFactory

_TOKEN = "auto-interner-browser-smoke"


def _enabled(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def main() -> int:
    """Open an in-memory page and always close the browser process."""
    binary = Path(os.environ.get("CHROMIUM_BINARY", "/usr/bin/chromium"))
    driver = Path(os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver"))
    if not binary.is_file() or not driver.is_file():
        return 1
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
        return 0 if _TOKEN in session.page_source else 1
    except Exception:
        return 1
    finally:
        if session is not None:
            with suppress(Exception):
                session.quit()


if __name__ == "__main__":  # pragma: no cover - exercised by the arm64 image
    raise SystemExit(main())
