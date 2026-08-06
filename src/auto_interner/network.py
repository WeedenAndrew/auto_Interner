"""Pinned-address HTTP GETs with URL, redirect, timeout, and size controls."""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

_NUMERIC_HOST_PATTERN = re.compile(r"^(?:0x[0-9a-f]+|[0-9.]+)$", re.IGNORECASE)


class NetworkFailure(RuntimeError):
    """Sanitized network failure safe to persist in local state."""

    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


class TransportTimeout(TimeoutError):
    """Transport timed out before a complete bounded response arrived."""


class TransportConnectionError(ConnectionError):
    """Transport could not complete a request to a validated address."""


class TransportResponseTooLarge(ValueError):
    """Transport response exceeded the configured byte limit."""


class HostResolver(Protocol):
    """Replaceable DNS boundary used before any connection is attempted."""

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        """Return every address currently advertised for the host."""


class SocketHostResolver:
    """Resolve TCP addresses through the operating system."""

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        addresses: list[str] = []
        for result in socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        ):
            address = str(result[4][0])
            if address not in addresses:
                addresses.append(address)
        return tuple(addresses)


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """Validated URL plus the exact public addresses a transport may use."""

    url: str
    scheme: str
    hostname: str
    port: int
    host_header: str
    request_target: str
    addresses: tuple[str, ...]


class PublicUrlPolicy:
    """Allow only credential-free HTTP(S) targets resolving entirely public."""

    def __init__(self, resolver: HostResolver | None = None, *, max_url_length: int = 4096) -> None:
        if max_url_length <= 0:
            raise ValueError("max_url_length must be positive")
        self._resolver = resolver or SocketHostResolver()
        self._max_url_length = max_url_length

    @staticmethod
    def _parse(url: str) -> tuple[SplitResult, str, int]:
        if not url or len(url) > 4096:
            raise NetworkFailure("URL is empty or too long", retryable=False)
        parsed = urlsplit(url)
        if parsed.scheme.casefold() not in {"http", "https"}:
            raise NetworkFailure("URL scheme is not HTTP(S)", retryable=False)
        if parsed.username is not None or parsed.password is not None:
            raise NetworkFailure("URL must not contain credentials", retryable=False)
        if parsed.hostname is None:
            raise NetworkFailure("URL hostname is missing", retryable=False)
        try:
            port = parsed.port
        except ValueError as exc:
            raise NetworkFailure("URL port is invalid", retryable=False) from exc
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").casefold()
        if not hostname or hostname == "localhost" or hostname.endswith(".localhost"):
            raise NetworkFailure("URL hostname is not public", retryable=False)
        return parsed, hostname, port or (443 if parsed.scheme.casefold() == "https" else 80)

    @staticmethod
    def _require_public_address(value: str) -> str:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise NetworkFailure(
                "host resolution returned an invalid address", retryable=False
            ) from exc
        if not address.is_global:
            raise NetworkFailure("URL resolves to a non-public address", retryable=False)
        return address.compressed

    def resolve(self, url: str) -> ResolvedTarget:
        """Validate and resolve one URL before a transport connection."""
        if len(url) > self._max_url_length:
            raise NetworkFailure("URL is empty or too long", retryable=False)
        parsed, hostname, port = self._parse(url)
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            if _NUMERIC_HOST_PATTERN.fullmatch(hostname):
                raise NetworkFailure(
                    "URL resolves to a non-public address", retryable=False
                ) from None
            try:
                raw_addresses = self._resolver.resolve(hostname, port)
            except OSError as exc:
                raise NetworkFailure("host resolution failed", retryable=True) from exc
            if not raw_addresses:
                raise NetworkFailure(
                    "host resolution returned no addresses", retryable=True
                ) from None
        else:
            raw_addresses = (literal.compressed,)

        addresses = tuple(
            dict.fromkeys(self._require_public_address(item) for item in raw_addresses)
        )
        scheme = parsed.scheme.casefold()
        default_port = 443 if scheme == "https" else 80
        display_host = f"[{hostname}]" if ":" in hostname else hostname
        host_header = display_host if port == default_port else f"{display_host}:{port}"
        request_target = parsed.path or "/"
        if parsed.query:
            request_target = f"{request_target}?{parsed.query}"
        normalized_url = urlunsplit((scheme, host_header, parsed.path, parsed.query, ""))
        return ResolvedTarget(
            url=normalized_url,
            scheme=scheme,
            hostname=hostname,
            port=port,
            host_header=host_header,
            request_target=request_target,
            addresses=addresses,
        )


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Bounded response returned after all redirects are validated."""

    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        return self.headers.get(name.casefold())


class HttpTransport(Protocol):
    """Connection boundary receiving only a prevalidated pinned address."""

    def get(
        self,
        target: ResolvedTarget,
        address: str,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        user_agent: str,
    ) -> HttpResponse:
        """Perform one GET without following redirects."""


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        address: str,
        port: int,
        *,
        server_hostname: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(address, port, timeout=timeout, context=context)
        self._validated_server_hostname = server_hostname
        self._validation_context = context

    def connect(self) -> None:
        raw_socket = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._validation_context.wrap_socket(
            raw_socket,
            server_hostname=self._validated_server_hostname,
        )


class PinnedHttpTransport:
    """Standard-library transport that connects to the validated address directly."""

    def __init__(self, *, ssl_context: ssl.SSLContext | None = None) -> None:
        self._ssl_context = ssl_context or ssl.create_default_context()

    def get(
        self,
        target: ResolvedTarget,
        address: str,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        user_agent: str,
    ) -> HttpResponse:
        if timeout_seconds <= 0 or max_response_bytes <= 0:
            raise ValueError("timeout and response limit must be positive")
        if address not in target.addresses:
            raise ValueError("transport address was not validated for this target")

        if target.scheme == "https":
            connection: http.client.HTTPConnection = _PinnedHttpsConnection(
                address,
                target.port,
                server_hostname=target.hostname,
                timeout=timeout_seconds,
                context=self._ssl_context,
            )
        else:
            connection = http.client.HTTPConnection(address, target.port, timeout=timeout_seconds)

        try:
            connection.request(
                "GET",
                target.request_target,
                headers={
                    "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.1",
                    "Host": target.host_header,
                    "User-Agent": user_agent,
                },
            )
            response = connection.getresponse()
            declared_length = response.getheader("Content-Length")
            if declared_length is not None:
                try:
                    parsed_length = int(declared_length)
                except ValueError:
                    parsed_length = None
                if parsed_length is not None and parsed_length > max_response_bytes:
                    raise TransportResponseTooLarge
            body = response.read(max_response_bytes + 1)
            if len(body) > max_response_bytes:
                raise TransportResponseTooLarge
            headers = {name.casefold(): value for name, value in response.getheaders()}
            return HttpResponse(target.url, response.status, headers, body)
        except TimeoutError as exc:
            raise TransportTimeout from exc
        except TransportResponseTooLarge:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise TransportConnectionError from exc
        finally:
            connection.close()


class SafeHttpClient:
    """Bounded GET client that revalidates every redirect target."""

    _REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

    def __init__(
        self,
        *,
        url_policy: PublicUrlPolicy | None = None,
        transport: HttpTransport | None = None,
        timeout_seconds: float = 15.0,
        max_response_bytes: int = 5 * 1024 * 1024,
        max_redirects: int = 5,
        user_agent: str = "AutoInterner/0.1 (+local internship screening)",
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects must not be negative")
        self._url_policy = url_policy or PublicUrlPolicy()
        self._transport = transport or PinnedHttpTransport()
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_redirects = max_redirects
        self._user_agent = user_agent

    def _request_target(self, target: ResolvedTarget) -> HttpResponse:
        last_failure: Exception | None = None
        for address in target.addresses:
            try:
                return self._transport.get(
                    target,
                    address,
                    timeout_seconds=self._timeout_seconds,
                    max_response_bytes=self._max_response_bytes,
                    user_agent=self._user_agent,
                )
            except TransportTimeout as exc:
                last_failure = exc
            except TransportConnectionError as exc:
                last_failure = exc
            except TransportResponseTooLarge as exc:
                raise NetworkFailure("response exceeded the byte limit", retryable=False) from exc
        if isinstance(last_failure, TransportTimeout):
            raise NetworkFailure("request timed out", retryable=True) from last_failure
        raise NetworkFailure("connection failed", retryable=True) from last_failure

    def get(self, url: str) -> HttpResponse:
        """GET a public URL and return only a successful bounded response."""
        current_url = url
        for redirect_count in range(self._max_redirects + 1):
            target = self._url_policy.resolve(current_url)
            response = self._request_target(target)
            if response.status in self._REDIRECT_STATUSES:
                location = response.header("location")
                if location is None:
                    raise NetworkFailure("redirect response omitted Location", retryable=False)
                if redirect_count == self._max_redirects:
                    raise NetworkFailure("redirect limit exceeded", retryable=False)
                current_url = urljoin(target.url, location)
                continue
            if 200 <= response.status < 300:
                return response
            if response.status in {408, 425, 429} or 500 <= response.status < 600:
                raise NetworkFailure("remote server returned a temporary error", retryable=True)
            raise NetworkFailure("remote server rejected the request", retryable=False)
        raise AssertionError("redirect loop escaped its bound")
