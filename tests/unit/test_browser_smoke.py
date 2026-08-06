"""Offline target-browser compatibility command tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_interner.browser_smoke import main

pytestmark = [pytest.mark.unit, pytest.mark.browser]


class FakeSession:
    current_url = "data:text/html"
    page_source = ""

    def __init__(self) -> None:
        self.quit_calls = 0

    def set_page_load_timeout(self, seconds: float) -> None:
        assert seconds == 30

    def set_script_timeout(self, seconds: float) -> None:
        assert seconds == 30

    def get(self, url: str) -> None:
        assert url.startswith("data:text/html")
        self.page_source = url

    def quit(self) -> None:
        self.quit_calls += 1


def test_browser_smoke_uses_configured_packages_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "chromium"
    driver = tmp_path / "chromedriver"
    binary.touch()
    driver.touch()
    session = FakeSession()
    received: dict[str, object] = {}

    class FakeFactory:
        def __init__(self, **kwargs: object) -> None:
            received.update(kwargs)

        def create(self) -> FakeSession:
            return session

    monkeypatch.setenv("CHROMIUM_BINARY", str(binary))
    monkeypatch.setenv("CHROMEDRIVER_PATH", str(driver))
    monkeypatch.setenv("BROWSER_NO_SANDBOX", "true")
    monkeypatch.setattr("auto_interner.browser_smoke.SeleniumChromeFactory", FakeFactory)

    assert main() == 0
    assert received == {
        "chromium_binary": binary,
        "chromedriver_path": driver,
        "no_sandbox": True,
    }
    assert session.quit_calls == 1


def test_browser_smoke_fails_before_start_for_missing_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHROMIUM_BINARY", str(tmp_path / "missing"))
    monkeypatch.setenv("CHROMEDRIVER_PATH", str(tmp_path / "also-missing"))

    assert main() == 1
