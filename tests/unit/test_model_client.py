"""Anthropic Messages adapter contract tests with a fully local fake connection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from auto_interner.model_client import AnthropicMessagesClient, ModelBoundaryError

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.security]


@dataclass
class FakeResponse:
    status: int = 200
    payload: object = field(
        default_factory=lambda: {
            "content": [
                {
                    "type": "tool_use",
                    "id": "fictional-tool-id",
                    "name": "screen",
                    "input": {"safe": True},
                }
            ]
        }
    )
    declared_length: str | None = None

    def getheader(self, name: str) -> str | None:
        assert name == "Content-Length"
        return self.declared_length

    def read(self, amount: int) -> bytes:
        return json.dumps(self.payload).encode()[:amount]


@dataclass
class FakeConnection:
    response: FakeResponse
    error: Exception | None = None
    request_args: tuple[object, ...] | None = None
    request_kwargs: dict[str, object] | None = None
    closed: bool = False

    def request(self, *args: object, **kwargs: object) -> None:
        self.request_args = args
        self.request_kwargs = kwargs
        if self.error is not None:
            raise self.error

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def _client(connection: FakeConnection, **kwargs: object) -> AnthropicMessagesClient:
    return AnthropicMessagesClient(
        api_key="fictional-key",
        model="fictional-model",
        connection_factory=lambda host, timeout: connection,
        **kwargs,
    )


def _call(client: AnthropicMessagesClient) -> object:
    return client.call_tool(
        tool_name="screen",
        input_schema={"type": "object"},
        system_prompt="system",
        user_prompt="posting",
    )


def test_forces_named_strict_tool_at_fixed_endpoint() -> None:
    connection = FakeConnection(FakeResponse())

    assert _call(_client(connection)) == {"safe": True}

    assert connection.request_args == ("POST", "/v1/messages")
    assert connection.request_kwargs is not None
    request = json.loads(connection.request_kwargs["body"])
    assert request["model"] == "fictional-model"
    assert request["tool_choice"] == {"type": "tool", "name": "screen"}
    assert request["tools"][0]["strict"] is True
    headers = connection.request_kwargs["headers"]
    assert headers["x-api-key"] == "fictional-key"
    assert connection.closed


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(400, False), (401, False), (408, True), (429, True), (500, True)],
)
def test_http_errors_are_sanitized_and_classified(status: int, retryable: bool) -> None:
    with pytest.raises(ModelBoundaryError) as captured:
        _call(_client(FakeConnection(FakeResponse(status=status))))

    assert captured.value.retryable is retryable
    assert "fictional-key" not in captured.value.reason


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"content": "wrong"},
        {"content": []},
        {"content": [{"type": "text", "text": "not a tool"}]},
        {
            "content": [
                {"type": "tool_use", "name": "other", "input": {}},
                {"type": "tool_use", "name": "screen", "input": {}},
                {"type": "tool_use", "name": "screen", "input": {}},
            ]
        },
    ],
)
def test_invalid_or_ambiguous_envelopes_are_retryable(payload: object) -> None:
    with pytest.raises(ModelBoundaryError) as captured:
        _call(_client(FakeConnection(FakeResponse(payload=payload))))

    assert captured.value.retryable is True


def test_declared_and_actual_response_limits_are_enforced() -> None:
    declared = FakeConnection(FakeResponse(declared_length="101"))
    with pytest.raises(ModelBoundaryError, match="byte limit") as captured:
        _call(_client(declared, max_response_bytes=100))
    assert captured.value.retryable is False

    actual = FakeConnection(FakeResponse(payload={"content": [], "padding": "x" * 500}))
    with pytest.raises(ModelBoundaryError, match="byte limit"):
        _call(_client(actual, max_response_bytes=100))


def test_transport_failure_is_retryable_and_connection_closes() -> None:
    connection = FakeConnection(FakeResponse(), error=TimeoutError())

    with pytest.raises(ModelBoundaryError, match="timed out") as captured:
        _call(_client(connection))

    assert captured.value.retryable is True
    assert connection.closed


def test_constructor_rejects_empty_or_nonpositive_configuration() -> None:
    with pytest.raises(ValueError):
        AnthropicMessagesClient(api_key="", model="m")
    with pytest.raises(ValueError):
        AnthropicMessagesClient(api_key="k", model="")
    with pytest.raises(ValueError):
        AnthropicMessagesClient(api_key="k", model="m", max_tokens=0)
