"""Safe HTTP and NF-SEC URL-policy cases with no live connections."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from auto_interner.network import (
    HttpResponse,
    NetworkFailure,
    PinnedHttpTransport,
    PublicUrlPolicy,
    ResolvedTarget,
    SafeHttpClient,
    SocketHostResolver,
    TransportConnectionError,
    TransportResponseTooLarge,
    TransportTimeout,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]


@dataclass
class FakeResolver:
    addresses: dict[str, tuple[str, ...]]
    calls: list[tuple[str, int]] = field(default_factory=list)

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        value = self.addresses.get(hostname)
        if value is None:
            raise OSError("fictional DNS failure")
        return value


@dataclass
class FakeTransport:
    responses: dict[str, HttpResponse | Exception]
    calls: list[tuple[str, str, float, int, str]] = field(default_factory=list)

    def get(
        self,
        target: ResolvedTarget,
        address: str,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        user_agent: str,
    ) -> HttpResponse:
        self.calls.append((target.url, address, timeout_seconds, max_response_bytes, user_agent))
        response = self.responses[target.url]
        if isinstance(response, Exception):
            raise response
        return response


def _response(
    url: str,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    body: bytes = b"ok",
) -> HttpResponse:
    return HttpResponse(url, status, headers or {}, body)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/job",
        "http://LOCALHOST./job",
        "http://jobs.localhost/job",
        "http://127.0.0.1/job",
        "http://127.1/job",
        "http://0.0.0.0/job",
    ],
)
def test_nf_sec_001_localhost_and_loopback_are_blocked(url: str) -> None:
    with pytest.raises(NetworkFailure, match="public") as captured:
        PublicUrlPolicy(FakeResolver({})).resolve(url)

    assert captured.value.retryable is False


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1/job",
        "http://172.16.0.1/job",
        "http://192.168.1.1/job",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_nf_sec_002_private_ipv4_ranges_are_blocked(url: str) -> None:
    with pytest.raises(NetworkFailure, match="non-public"):
        PublicUrlPolicy(FakeResolver({})).resolve(url)


@pytest.mark.parametrize(
    "url",
    ["http://[::1]/job", "http://[fe80::1]/job", "http://[fc00::1]/job"],
)
def test_nf_sec_003_private_ipv6_ranges_are_blocked(url: str) -> None:
    with pytest.raises(NetworkFailure, match="non-public"):
        PublicUrlPolicy(FakeResolver({})).resolve(url)


def test_dns_answer_with_any_private_address_is_entirely_blocked() -> None:
    resolver = FakeResolver({"jobs.example": ("93.184.216.34", "127.0.0.1")})

    with pytest.raises(NetworkFailure, match="non-public"):
        PublicUrlPolicy(resolver).resolve("https://jobs.example/role")


@pytest.mark.parametrize("scheme", ["file", "ftp", "data", "gopher", "custom"])
def test_nf_sec_005_non_http_schemes_are_rejected(scheme: str) -> None:
    with pytest.raises(NetworkFailure, match=r"HTTP\(S\)"):
        PublicUrlPolicy(FakeResolver({})).resolve(f"{scheme}://example.com/value")


def test_credentials_missing_hosts_and_invalid_ports_are_rejected() -> None:
    policy = PublicUrlPolicy(FakeResolver({}))

    with pytest.raises(NetworkFailure, match="credentials"):
        policy.resolve("https://user:secret@example.com/job")
    with pytest.raises(NetworkFailure, match="hostname"):
        policy.resolve("https:///job")
    with pytest.raises(NetworkFailure, match="port"):
        policy.resolve("https://example.com:99999/job")


def test_public_url_is_normalized_and_resolved_before_transport() -> None:
    resolver = FakeResolver({"jobs.example": ("93.184.216.34",)})
    target = PublicUrlPolicy(resolver).resolve("HTTPS://Jobs.Example:443/path?q=1#fragment")

    assert target.url == "https://jobs.example/path?q=1"
    assert target.request_target == "/path?q=1"
    assert target.host_header == "jobs.example"
    assert target.addresses == ("93.184.216.34",)


def test_f_fet_010_public_redirect_is_revalidated_and_allowed() -> None:
    resolver = FakeResolver(
        {
            "first.example": ("93.184.216.34",),
            "second.example": ("1.1.1.1",),
        }
    )
    transport = FakeTransport(
        {
            "https://first.example/start": _response(
                "https://first.example/start",
                status=302,
                headers={"location": "https://second.example/job"},
            ),
            "https://second.example/job": _response("https://second.example/job", body=b"posting"),
        }
    )
    client = SafeHttpClient(
        url_policy=PublicUrlPolicy(resolver), transport=transport, max_redirects=2
    )

    result = client.get("https://first.example/start")

    assert result.body == b"posting"
    assert [call[0] for call in transport.calls] == [
        "https://first.example/start",
        "https://second.example/job",
    ]


def test_nf_sec_004_public_redirect_to_private_is_blocked_before_connection() -> None:
    resolver = FakeResolver({"first.example": ("93.184.216.34",)})
    transport = FakeTransport(
        {
            "https://first.example/start": _response(
                "https://first.example/start",
                status=302,
                headers={"location": "http://169.254.169.254/latest/meta-data"},
            )
        }
    )
    client = SafeHttpClient(url_policy=PublicUrlPolicy(resolver), transport=transport)

    with pytest.raises(NetworkFailure, match="non-public"):
        client.get("https://first.example/start")

    assert len(transport.calls) == 1


def test_redirect_without_location_or_beyond_limit_fails_permanently() -> None:
    resolver = FakeResolver({"jobs.example": ("93.184.216.34",)})
    missing = FakeTransport(
        {"https://jobs.example/one": _response("https://jobs.example/one", status=302)}
    )
    with pytest.raises(NetworkFailure, match="Location") as captured:
        SafeHttpClient(url_policy=PublicUrlPolicy(resolver), transport=missing).get(
            "https://jobs.example/one"
        )
    assert captured.value.retryable is False

    looping = FakeTransport(
        {
            "https://jobs.example/one": _response(
                "https://jobs.example/one",
                status=302,
                headers={"location": "/one"},
            )
        }
    )
    with pytest.raises(NetworkFailure, match="redirect limit"):
        SafeHttpClient(
            url_policy=PublicUrlPolicy(resolver),
            transport=looping,
            max_redirects=1,
        ).get("https://jobs.example/one")


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(408, True), (429, True), (503, True), (404, False), (403, False)],
)
def test_http_status_is_classified_without_response_body_leakage(
    status: int, retryable: bool
) -> None:
    resolver = FakeResolver({"jobs.example": ("93.184.216.34",)})
    transport = FakeTransport(
        {
            "https://jobs.example/role": _response(
                "https://jobs.example/role", status=status, body=b"private server detail"
            )
        }
    )

    with pytest.raises(NetworkFailure) as captured:
        SafeHttpClient(url_policy=PublicUrlPolicy(resolver), transport=transport).get(
            "https://jobs.example/role"
        )

    assert captured.value.retryable is retryable
    assert "private server detail" not in captured.value.reason


@pytest.mark.parametrize(
    ("error", "reason", "retryable"),
    [
        (TransportTimeout(), "timed out", True),
        (TransportConnectionError(), "connection failed", True),
        (TransportResponseTooLarge(), "byte limit", False),
    ],
)
def test_transport_failures_are_sanitized_and_classified(
    error: Exception, reason: str, retryable: bool
) -> None:
    resolver = FakeResolver({"jobs.example": ("93.184.216.34",)})
    transport = FakeTransport({"https://jobs.example/role": error})

    with pytest.raises(NetworkFailure, match=reason) as captured:
        SafeHttpClient(url_policy=PublicUrlPolicy(resolver), transport=transport).get(
            "https://jobs.example/role"
        )

    assert captured.value.retryable is retryable


def test_client_tries_each_prevalidated_address_after_connection_failure() -> None:
    resolver = FakeResolver({"jobs.example": ("93.184.216.34", "1.1.1.1")})

    @dataclass
    class AddressTransport:
        calls: list[str] = field(default_factory=list)

        def get(
            self,
            target: ResolvedTarget,
            address: str,
            *,
            timeout_seconds: float,
            max_response_bytes: int,
            user_agent: str,
        ) -> HttpResponse:
            del timeout_seconds, max_response_bytes, user_agent
            self.calls.append(address)
            if address == "93.184.216.34":
                raise TransportConnectionError
            return _response(target.url)

    transport = AddressTransport()
    response = SafeHttpClient(url_policy=PublicUrlPolicy(resolver), transport=transport).get(
        "https://jobs.example/role"
    )

    assert response.status == 200
    assert transport.calls == ["93.184.216.34", "1.1.1.1"]


def test_socket_resolver_deduplicates_operating_system_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (10, 1, 6, "", ("2606:4700:4700::1111", 443, 0, 0)),
    ]
    monkeypatch.setattr("auto_interner.network.socket.getaddrinfo", lambda *args, **kwargs: answers)

    assert SocketHostResolver().resolve("jobs.example", 443) == (
        "93.184.216.34",
        "2606:4700:4700::1111",
    )


@dataclass
class FakeRawResponse:
    status: int = 200
    body: bytes = b"response"
    declared_length: str | None = None

    def getheader(self, name: str) -> str | None:
        assert name == "Content-Length"
        return self.declared_length

    def read(self, amount: int) -> bytes:
        return self.body[:amount]

    def getheaders(self) -> list[tuple[str, str]]:
        return [("Content-Type", "text/plain")]


@dataclass
class FakeConnection:
    response: FakeRawResponse
    request_error: Exception | None = None
    closed: bool = False
    request_headers: dict[str, str] | None = None

    def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
        assert method == "GET"
        assert target == "/role"
        self.request_headers = headers
        if self.request_error is not None:
            raise self.request_error

    def getresponse(self) -> FakeRawResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def _resolved_http_target() -> ResolvedTarget:
    return ResolvedTarget(
        url="http://jobs.example/role",
        scheme="http",
        hostname="jobs.example",
        port=80,
        host_header="jobs.example",
        request_target="/role",
        addresses=("93.184.216.34",),
    )


def test_pinned_transport_uses_validated_address_and_bounded_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(FakeRawResponse())
    monkeypatch.setattr(
        "auto_interner.network.http.client.HTTPConnection",
        lambda *args, **kwargs: connection,
    )

    response = PinnedHttpTransport().get(
        _resolved_http_target(),
        "93.184.216.34",
        timeout_seconds=3,
        max_response_bytes=20,
        user_agent="fixture-agent",
    )

    assert response.body == b"response"
    assert response.header("content-type") == "text/plain"
    assert connection.request_headers == {
        "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.1",
        "Host": "jobs.example",
        "User-Agent": "fixture-agent",
    }
    assert connection.closed


@pytest.mark.parametrize(
    "raw_response",
    [
        FakeRawResponse(body=b"small", declared_length="21"),
        FakeRawResponse(body=b"a" * 21),
    ],
)
def test_pinned_transport_enforces_declared_and_actual_size_limits(
    raw_response: FakeRawResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = FakeConnection(raw_response)
    monkeypatch.setattr(
        "auto_interner.network.http.client.HTTPConnection",
        lambda *args, **kwargs: connection,
    )

    with pytest.raises(TransportResponseTooLarge):
        PinnedHttpTransport().get(
            _resolved_http_target(),
            "93.184.216.34",
            timeout_seconds=3,
            max_response_bytes=20,
            user_agent="fixture-agent",
        )

    assert connection.closed


@pytest.mark.parametrize(
    ("error", "expected"),
    [(TimeoutError(), TransportTimeout), (OSError(), TransportConnectionError)],
)
def test_pinned_transport_classifies_errors_and_closes(
    error: Exception,
    expected: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(FakeRawResponse(), request_error=error)
    monkeypatch.setattr(
        "auto_interner.network.http.client.HTTPConnection",
        lambda *args, **kwargs: connection,
    )

    with pytest.raises(expected):
        PinnedHttpTransport().get(
            _resolved_http_target(),
            "93.184.216.34",
            timeout_seconds=3,
            max_response_bytes=20,
            user_agent="fixture-agent",
        )

    assert connection.closed


def test_pinned_transport_rejects_unvalidated_address_before_connection() -> None:
    with pytest.raises(ValueError, match="not validated"):
        PinnedHttpTransport().get(
            _resolved_http_target(),
            "1.1.1.1",
            timeout_seconds=3,
            max_response_bytes=20,
            user_agent="fixture-agent",
        )
