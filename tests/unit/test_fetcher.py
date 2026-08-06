"""F-FET static-first, extraction, browser, and cleanup cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from auto_interner.fetcher import (
    BrowserFetchError,
    SeleniumBrowserFetcher,
    SeleniumChromeFactory,
    StaticFirstPostingFetcher,
    extract_response_text,
    is_usable_posting_text,
)
from auto_interner.models import FetchMethod, FetchStatus, Listing
from auto_interner.network import (
    HttpResponse,
    NetworkFailure,
    PublicUrlPolicy,
    SafeHttpClient,
)

pytestmark = pytest.mark.unit


def _listing(listing_id: str = "fixture-one") -> Listing:
    return Listing(
        id=listing_id,
        company_name="Fictional Systems",
        title="Software Intern",
        url="https://jobs.example/role",
        locations=("Denver, CO",),
        active=True,
    )


def _long_text(label: str = "posting") -> str:
    return f"{label} " + "Build reliable software with a collaborative engineering team. " * 8


class FakeClient:
    def __init__(self, response: HttpResponse | NetworkFailure) -> None:
        self.response = response
        self.calls: list[str] = []

    def get(self, url: str) -> HttpResponse:
        self.calls.append(url)
        if isinstance(self.response, NetworkFailure):
            raise self.response
        return self.response


class FakeBrowser:
    def __init__(self, response: str | BrowserFetchError) -> None:
        self.response = response
        self.calls: list[str] = []

    def fetch(self, url: str) -> str:
        self.calls.append(url)
        if isinstance(self.response, BrowserFetchError):
            raise self.response
        return self.response


def _fetcher(
    response: HttpResponse | NetworkFailure,
    *,
    browser: FakeBrowser | None = None,
    minimum_characters: int = 100,
) -> StaticFirstPostingFetcher:
    client = cast(SafeHttpClient, FakeClient(response))
    return StaticFirstPostingFetcher(
        client,
        browser=browser,
        minimum_characters=minimum_characters,
    )


def test_f_fet_001_and_011_static_html_returns_normalized_readable_text() -> None:
    html = f"""
    <html><body><main><h1>Software Intern</h1><p>{_long_text()}</p>
    <script>privateExecutableValue()</script><style>.hidden {{ display: none; }}</style>
    </main></body></html>
    """
    response = HttpResponse(
        "https://jobs.example/role",
        200,
        {"content-type": "text/html; charset=utf-8"},
        html.encode(),
    )

    result = _fetcher(response).fetch(_listing(), attempt_number=1)

    assert result.status is FetchStatus.SUCCESS
    assert result.method is FetchMethod.STATIC
    assert "Software Intern" in result.text
    assert "privateExecutableValue" not in result.text
    assert result.content_hash is not None


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<html><body><div id='root'></div></body></html>",
        b"<html><body>You need to enable JavaScript to run this app.</body></html>",
    ],
)
def test_f_fet_002_and_003_empty_short_or_js_shell_requests_browser(body: bytes) -> None:
    response = HttpResponse("https://jobs.example/role", 200, {"content-type": "text/html"}, body)
    browser = FakeBrowser(_long_text("rendered"))

    result = _fetcher(response, browser=browser).fetch(_listing(), attempt_number=1)

    assert result.status is FetchStatus.SUCCESS
    assert result.method is FetchMethod.BROWSER
    assert browser.calls == ["https://jobs.example/role"]


def test_f_fet_004_complete_static_body_never_starts_browser() -> None:
    response = HttpResponse(
        "https://jobs.example/role",
        200,
        {"content-type": "text/plain"},
        _long_text().encode(),
    )
    browser = FakeBrowser(_long_text("unused"))

    result = _fetcher(response, browser=browser).fetch(_listing(), attempt_number=1)

    assert result.method is FetchMethod.STATIC
    assert browser.calls == []


def test_f_fet_005_static_timeout_follows_browser_fallback_policy() -> None:
    browser = FakeBrowser(_long_text("rendered"))
    fetcher = _fetcher(NetworkFailure("request timed out", retryable=True), browser=browser)

    result = fetcher.fetch(_listing(), attempt_number=2)

    assert result.status is FetchStatus.SUCCESS
    assert result.method is FetchMethod.BROWSER


def test_f_fet_007_browser_failure_is_retryable_and_sanitized() -> None:
    response = HttpResponse("https://jobs.example/role", 200, {"content-type": "text/html"}, b"")
    browser = FakeBrowser(BrowserFetchError("browser navigation failed"))

    result = _fetcher(response, browser=browser).fetch(_listing(), attempt_number=1)

    assert result.status is FetchStatus.RETRYABLE_FAILURE
    assert result.failure_reason == "browser navigation failed"


def test_unsafe_static_url_is_permanent_and_never_starts_browser() -> None:
    browser = FakeBrowser(_long_text("unused"))
    fetcher = _fetcher(
        NetworkFailure("URL resolves to a non-public address", retryable=False),
        browser=browser,
    )

    result = fetcher.fetch(_listing(), attempt_number=1)

    assert result.status is FetchStatus.PERMANENT_FAILURE
    assert browser.calls == []


def test_missing_browser_fallback_remains_retryable() -> None:
    response = HttpResponse("https://jobs.example/role", 200, {"content-type": "text/html"}, b"")

    result = _fetcher(response).fetch(_listing(), attempt_number=1)

    assert result.status is FetchStatus.RETRYABLE_FAILURE
    assert "fallback is unavailable" in (result.failure_reason or "")


def test_browser_short_text_remains_retryable() -> None:
    response = HttpResponse("https://jobs.example/role", 200, {"content-type": "text/html"}, b"")

    result = _fetcher(response, browser=FakeBrowser("short")).fetch(_listing(), attempt_number=1)

    assert result.status is FetchStatus.RETRYABLE_FAILURE
    assert "no usable" in (result.failure_reason or "")


@pytest.mark.parametrize(
    ("content_type", "body", "expected"),
    [
        ("text/plain; charset=iso-8859-1", "Développeur".encode("iso-8859-1"), "Développeur"),
        ("text/html", b"<p>Visible</p><script>Hidden</script>", "Visible"),
    ],
)
def test_f_fet_012_valid_encodings_decode_and_scripts_are_removed(
    content_type: str, body: bytes, expected: str
) -> None:
    assert extract_response_text(body, content_type) == expected


@pytest.mark.parametrize(
    ("content_type", "body", "reason"),
    [
        ("application/pdf", b"value", "media type"),
        ("text/plain; charset=not-a-codec", b"value", "unknown character"),
        ("text/plain; charset=utf-8", b"\xff", "could not be decoded"),
    ],
)
def test_invalid_content_returns_permanent_sanitized_failure(
    content_type: str, body: bytes, reason: str
) -> None:
    response = HttpResponse("https://jobs.example/role", 200, {"content-type": content_type}, body)

    result = _fetcher(response, minimum_characters=1).fetch(_listing(), attempt_number=1)

    assert result.status is FetchStatus.PERMANENT_FAILURE
    assert reason in (result.failure_reason or "")


def test_f_fet_013_shared_url_retains_independent_listing_ids() -> None:
    response = HttpResponse(
        "https://jobs.example/role",
        200,
        {"content-type": "text/plain"},
        _long_text().encode(),
    )
    fetcher = _fetcher(response)

    first = fetcher.fetch(_listing("one"), attempt_number=1)
    second = fetcher.fetch(_listing("two"), attempt_number=1)

    assert first.listing_id == "one"
    assert second.listing_id == "two"


def test_usability_guard_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        is_usable_posting_text("value", minimum_characters=0)


@dataclass
class FakeResolver:
    addresses: tuple[str, ...] = ("93.184.216.34",)

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        del hostname, port
        return self.addresses


@dataclass
class FakeSession:
    page_source: str
    current_url: str = "https://jobs.example/role"
    fail_navigation: bool = False
    fail_quit: bool = False
    events: list[str] = field(default_factory=list)

    def set_page_load_timeout(self, seconds: float) -> None:
        self.events.append(f"page:{seconds}")

    def set_script_timeout(self, seconds: float) -> None:
        self.events.append(f"script:{seconds}")

    def get(self, url: str) -> None:
        self.events.append(f"get:{url}")
        if self.fail_navigation:
            raise TimeoutError("private driver detail")

    def quit(self) -> None:
        self.events.append("quit")
        if self.fail_quit:
            raise RuntimeError("private cleanup detail")


@dataclass
class FakeFactory:
    session: FakeSession

    def create(self) -> FakeSession:
        self.session.events.append("create")
        return self.session


def _browser_fetcher(session: FakeSession) -> SeleniumBrowserFetcher:
    return SeleniumBrowserFetcher(
        FakeFactory(session),
        url_policy=PublicUrlPolicy(FakeResolver()),
        timeout_seconds=12,
    )


def test_f_fet_006_browser_success_returns_text_and_closes_session() -> None:
    session = FakeSession(f"<main>{_long_text('rendered')}</main>")

    text = _browser_fetcher(session).fetch("https://jobs.example/role")

    assert "rendered" in text
    assert session.events == [
        "create",
        "page:12",
        "script:12",
        "get:https://jobs.example/role",
        "quit",
    ]


def test_f_fet_009_browser_navigation_failure_still_closes_session() -> None:
    session = FakeSession("", fail_navigation=True)

    with pytest.raises(BrowserFetchError, match="navigation failed"):
        _browser_fetcher(session).fetch("https://jobs.example/role")

    assert session.events[-1] == "quit"


def test_browser_cleanup_failure_is_sanitized() -> None:
    session = FakeSession(f"<main>{_long_text()}</main>", fail_quit=True)

    with pytest.raises(BrowserFetchError, match="cleanup failed") as captured:
        _browser_fetcher(session).fetch("https://jobs.example/role")

    assert "private cleanup detail" not in str(captured.value)


def test_browser_revalidates_final_url_and_closes_on_private_redirect() -> None:
    session = FakeSession("value", current_url="http://127.0.0.1/private")

    with pytest.raises(BrowserFetchError, match="non-public") as captured:
        _browser_fetcher(session).fetch("https://jobs.example/role")

    assert captured.value.retryable is False
    assert session.events[-1] == "quit"


def test_browser_constructor_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="positive"):
        SeleniumBrowserFetcher(FakeFactory(FakeSession("")), timeout_seconds=0)


def test_static_fetcher_constructor_rejects_invalid_text_limit() -> None:
    client = cast(SafeHttpClient, FakeClient(NetworkFailure("unused", retryable=True)))

    with pytest.raises(ValueError, match="positive"):
        StaticFirstPostingFetcher(client, minimum_characters=0)


def test_selenium_factory_builds_headless_chrome_with_explicit_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = FakeSession("")

    class FakeOptions:
        def __init__(self) -> None:
            self.arguments: list[str] = []
            self.binary_location: str | None = None

        def add_argument(self, argument: str) -> None:
            self.arguments.append(argument)

    class FakeWebDriverModule:
        def __init__(self) -> None:
            self.options: FakeOptions | None = None
            self.service: object | None = None

        @staticmethod
        def ChromeOptions() -> FakeOptions:
            return FakeOptions()

        def Chrome(self, *, options: FakeOptions, service: object | None = None) -> FakeSession:
            self.options = options
            self.service = service
            return session

    @dataclass
    class FakeService:
        executable_path: str

    class FakeServiceModule:
        Service = FakeService

    webdriver = FakeWebDriverModule()

    def fake_import(name: str) -> object:
        if name == "selenium.webdriver":
            return webdriver
        if name == "selenium.webdriver.chrome.service":
            return FakeServiceModule
        raise AssertionError(name)

    monkeypatch.setattr("auto_interner.fetcher.importlib.import_module", fake_import)
    chromium = tmp_path / "chromium"
    driver_path = tmp_path / "chromedriver"

    created = SeleniumChromeFactory(
        chromium_binary=chromium,
        chromedriver_path=driver_path,
        no_sandbox=True,
    ).create()

    assert created is session
    assert webdriver.options is not None
    assert webdriver.options.binary_location == str(chromium)
    assert webdriver.options.arguments == [
        "--headless=new",
        "--incognito",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ]
    assert isinstance(webdriver.service, FakeService)
    assert webdriver.service.executable_path == str(driver_path)


def test_selenium_factory_reports_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_import(name: str) -> object:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("auto_interner.fetcher.importlib.import_module", missing_import)

    with pytest.raises(BrowserFetchError, match="optional dependency"):
        SeleniumChromeFactory().create()
