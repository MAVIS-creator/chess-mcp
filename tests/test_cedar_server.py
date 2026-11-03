from __future__ import annotations

from starlette.requests import Request

from app.cedar_server import _authorized, _bearer_token, _bounded_int


def _request(authorization: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request({"type": "http", "method": "POST", "path": "/api/analyze", "headers": headers})


def test_bearer_token_is_extracted() -> None:
    assert _bearer_token(_request("Bearer secret-value")) == "secret-value"
    assert _bearer_token(_request("Basic nope")) == ""
    assert _bearer_token(_request()) == ""


def test_authorization_uses_runtime_token(monkeypatch) -> None:
    monkeypatch.setenv("MCP_AUTH_TOKEN", "expected-token")
    assert _authorized(_request("Bearer expected-token")) is True
    assert _authorized(_request("Bearer wrong-token")) is False
    assert _authorized(_request()) is False


def test_missing_runtime_token_rejects_everything(monkeypatch) -> None:
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    assert _authorized(_request("Bearer expected-token")) is False


def test_bounded_int_clamps_and_defaults() -> None:
    assert _bounded_int("9", default=3, minimum=1, maximum=5) == 5
    assert _bounded_int("2", default=3, minimum=1, maximum=5) == 2
    assert _bounded_int("bad", default=3, minimum=1, maximum=5) == 3
