"""Live runtime composition without external calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_interner.composition import build_live_coordinator
from auto_interner.config import Settings
from auto_interner.fetcher import SeleniumBrowserFetcher

pytestmark = pytest.mark.unit


def test_live_composition_enables_isolated_browser_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    base_resume = data_dir / "2027" / "baseplate" / "base_resume.docx"
    base_resume.parent.mkdir(parents=True)
    base_resume.write_bytes(b"fictional composition placeholder")
    binary = tmp_path / "chromium"
    driver = tmp_path / "chromedriver"
    binary.touch()
    driver.touch()
    settings = Settings.from_env(
        {
            "RECRUITING_YEAR": "2027",
            "LISTINGS_SOURCE_MODE": "http",
            "LISTINGS_URL": "https://example.com/listings.json",
            "ANTHROPIC_MODEL": "fixture-model",
            "ANTHROPIC_API_KEY": "fixture-key",
            "DATA_DIR": str(data_dir),
            "STATE_DIR": str(tmp_path / "state"),
            "BROWSER_ENABLED": "true",
            "CHROMIUM_BINARY": str(binary),
            "CHROMEDRIVER_PATH": str(driver),
            "BROWSER_NO_SANDBOX": "true",
        }
    )
    captured: dict[str, object] = {}

    class FakePostingFetcher:
        def fetch(self, listing: object, *, attempt_number: int) -> object:
            del listing, attempt_number
            raise AssertionError("composition test does not fetch")

    def capture_fetcher(client: object, *, browser: object) -> FakePostingFetcher:
        captured["client"] = client
        captured["browser"] = browser
        return FakePostingFetcher()

    monkeypatch.setattr("auto_interner.composition.StaticFirstPostingFetcher", capture_fetcher)

    coordinator = build_live_coordinator(settings)

    assert coordinator is not None
    assert isinstance(captured["browser"], SeleniumBrowserFetcher)
