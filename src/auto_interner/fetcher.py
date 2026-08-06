"""Static-first posting retrieval with an optional Selenium browser fallback."""

from __future__ import annotations

import codecs
import importlib
import re
import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol, cast

from auto_interner.models import FetchMethod, FetchResult, FetchStatus, Listing
from auto_interner.network import NetworkFailure, PublicUrlPolicy, SafeHttpClient

_CHARSET_PATTERN = re.compile(r"\bcharset\s*=\s*[\"']?([^;\s\"']+)", re.IGNORECASE)
_HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_TEXT_MEDIA_TYPES = frozenset({"text/plain"})
_IGNORED_HTML_ELEMENTS = frozenset({"script", "style", "noscript", "svg", "template"})
_BLOCK_HTML_ELEMENTS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_JS_SHELL_MARKERS = (
    "enable javascript",
    "javascript is required",
    "please turn javascript on",
    "you need to enable javascript",
)


class PostingContentError(ValueError):
    """Sanitized decoding or media-type failure."""


class BrowserFetchError(RuntimeError):
    """Sanitized browser failure with retry classification."""

    def __init__(self, reason: str, *, retryable: bool = True) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized_tag = tag.casefold()
        if normalized_tag in _IGNORED_HTML_ELEMENTS:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and normalized_tag in _BLOCK_HTML_ELEMENTS:
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self._ignored_depth == 0 and tag.casefold() in _BLOCK_HTML_ELEMENTS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in _IGNORED_HTML_ELEMENTS and self._ignored_depth > 0:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and normalized_tag in _BLOCK_HTML_ELEMENTS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def normalize_readable_text(text: str) -> str:
    """Normalize Unicode and collapse markup-derived whitespace."""
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.split())


def extract_readable_html(document: str) -> str:
    """Extract non-executable readable text with the standard-library parser."""
    parser = _ReadableHtmlParser()
    parser.feed(document)
    parser.close()
    return normalize_readable_text("".join(parser.parts))


def _decode_body(body: bytes, content_type: str | None) -> tuple[str, bool]:
    raw_content_type = content_type or "text/html"
    media_type = raw_content_type.partition(";")[0].strip().casefold()
    if media_type not in _HTML_MEDIA_TYPES | _TEXT_MEDIA_TYPES:
        raise PostingContentError("posting response has an unsupported media type")

    charset_match = _CHARSET_PATTERN.search(raw_content_type)
    charset = charset_match.group(1) if charset_match is not None else "utf-8"
    try:
        codecs.lookup(charset)
    except LookupError as exc:
        raise PostingContentError(
            "posting response declares an unknown character encoding"
        ) from exc
    try:
        decoded = body.decode(charset)
    except UnicodeError as exc:
        raise PostingContentError("posting response could not be decoded") from exc
    return decoded, media_type in _HTML_MEDIA_TYPES


def extract_response_text(body: bytes, content_type: str | None) -> str:
    """Decode one HTTP body and remove scripts or markup when applicable."""
    decoded, is_html = _decode_body(body, content_type)
    return extract_readable_html(decoded) if is_html else normalize_readable_text(decoded)


def is_usable_posting_text(text: str, *, minimum_characters: int = 200) -> bool:
    """Return whether static or rendered text is substantial enough to screen."""
    if minimum_characters <= 0:
        raise ValueError("minimum_characters must be positive")
    normalized = normalize_readable_text(text)
    if len(normalized) < minimum_characters:
        return False
    lowered = normalized.casefold()
    return not any(marker in lowered for marker in _JS_SHELL_MARKERS)


class BrowserSession(Protocol):
    """Small Selenium-compatible surface used by the cleanup wrapper."""

    page_source: str
    current_url: str

    def set_page_load_timeout(self, seconds: float) -> None: ...

    def set_script_timeout(self, seconds: float) -> None: ...

    def get(self, url: str) -> None: ...

    def quit(self) -> None: ...


class BrowserSessionFactory(Protocol):
    """Create one isolated headless session for one fallback attempt."""

    def create(self) -> BrowserSession: ...


@dataclass(frozen=True, slots=True)
class SeleniumChromeFactory:
    """Lazy Selenium factory so static-only installs need no browser dependency."""

    chromium_binary: Path | None = None
    chromedriver_path: Path | None = None
    no_sandbox: bool = False
    disable_dev_shm_usage: bool = True

    def create(self) -> BrowserSession:
        try:
            webdriver = importlib.import_module("selenium.webdriver")
        except ModuleNotFoundError as exc:
            raise BrowserFetchError(
                "Selenium is not installed; install the browser optional dependency"
            ) from exc

        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--incognito")
        if self.disable_dev_shm_usage:
            options.add_argument("--disable-dev-shm-usage")
        if self.no_sandbox:
            options.add_argument("--no-sandbox")
        if self.chromium_binary is not None:
            options.binary_location = str(self.chromium_binary)

        if self.chromedriver_path is None:
            driver = webdriver.Chrome(options=options)
        else:
            service_module = importlib.import_module("selenium.webdriver.chrome.service")
            service = service_module.Service(executable_path=str(self.chromedriver_path))
            driver = webdriver.Chrome(service=service, options=options)
        return cast(BrowserSession, driver)


class SeleniumBrowserFetcher:
    """Render one public page and always close its browser session."""

    def __init__(
        self,
        factory: BrowserSessionFactory,
        *,
        url_policy: PublicUrlPolicy | None = None,
        timeout_seconds: float = 35.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._factory = factory
        self._url_policy = url_policy or PublicUrlPolicy()
        self._timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> str:
        """Return rendered text or a sanitized failure after guaranteed cleanup."""
        target = self._url_policy.resolve(url)
        session: BrowserSession | None = None
        result: str | None = None
        failure: BrowserFetchError | None = None
        try:
            session = self._factory.create()
            session.set_page_load_timeout(self._timeout_seconds)
            session.set_script_timeout(self._timeout_seconds)
            session.get(target.url)
            self._url_policy.resolve(session.current_url)
            result = extract_readable_html(session.page_source)
        except NetworkFailure as exc:
            failure = BrowserFetchError(exc.reason, retryable=exc.retryable)
        except BrowserFetchError as exc:
            failure = exc
        except Exception:
            failure = BrowserFetchError("browser navigation failed")
        finally:
            if session is not None:
                try:
                    session.quit()
                except Exception:
                    if failure is None:
                        failure = BrowserFetchError("browser cleanup failed")
        if failure is not None:
            raise failure
        if result is None:  # pragma: no cover - guarded state invariant
            raise AssertionError("browser fetch completed without a result")
        return result


class BrowserTextFetcher(Protocol):
    """Rendered-text boundary consumed by the static-first adapter."""

    def fetch(self, url: str) -> str: ...


class StaticFirstPostingFetcher:
    """Fetch readable posting text statically, then render only when necessary."""

    def __init__(
        self,
        client: SafeHttpClient,
        *,
        browser: BrowserTextFetcher | None = None,
        minimum_characters: int = 200,
    ) -> None:
        if minimum_characters <= 0:
            raise ValueError("minimum_characters must be positive")
        self._client = client
        self._browser = browser
        self._minimum_characters = minimum_characters

    @staticmethod
    def _failure(
        listing: Listing,
        attempt_number: int,
        reason: str,
        *,
        retryable: bool,
    ) -> FetchResult:
        return FetchResult(
            listing_id=listing.id,
            status=(FetchStatus.RETRYABLE_FAILURE if retryable else FetchStatus.PERMANENT_FAILURE),
            attempt_number=attempt_number,
            failure_reason=reason,
        )

    def _browser_result(
        self,
        listing: Listing,
        attempt_number: int,
        url: str,
    ) -> FetchResult:
        if self._browser is None:
            return self._failure(
                listing,
                attempt_number,
                "posting requires browser rendering but fallback is unavailable",
                retryable=True,
            )
        try:
            text = self._browser.fetch(url)
        except BrowserFetchError as exc:
            return self._failure(
                listing,
                attempt_number,
                exc.reason,
                retryable=exc.retryable,
            )
        if not is_usable_posting_text(text, minimum_characters=self._minimum_characters):
            return self._failure(
                listing,
                attempt_number,
                "browser returned no usable posting text",
                retryable=True,
            )
        normalized = normalize_readable_text(text)
        return FetchResult(
            listing_id=listing.id,
            status=FetchStatus.SUCCESS,
            attempt_number=attempt_number,
            method=FetchMethod.BROWSER,
            text=normalized,
            content_hash=sha256(normalized.encode("utf-8")).hexdigest(),
        )

    def fetch(self, listing: Listing, *, attempt_number: int) -> FetchResult:
        """Return a classified fetch result without writing pipeline state."""
        try:
            response = self._client.get(listing.url)
        except NetworkFailure as exc:
            if exc.retryable and self._browser is not None:
                return self._browser_result(listing, attempt_number, listing.url)
            return self._failure(
                listing,
                attempt_number,
                exc.reason,
                retryable=exc.retryable,
            )

        try:
            text = extract_response_text(response.body, response.header("content-type"))
        except PostingContentError as exc:
            return self._failure(
                listing,
                attempt_number,
                str(exc),
                retryable=False,
            )
        if not is_usable_posting_text(text, minimum_characters=self._minimum_characters):
            return self._browser_result(listing, attempt_number, response.url)

        return FetchResult(
            listing_id=listing.id,
            status=FetchStatus.SUCCESS,
            attempt_number=attempt_number,
            method=FetchMethod.STATIC,
            text=text,
            content_hash=sha256(text.encode("utf-8")).hexdigest(),
        )
