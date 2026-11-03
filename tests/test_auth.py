import asyncio

from app.auth import EnvironmentTokenVerifier


def test_token_verifier_accepts_configured_token(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "expected-token")

    result = asyncio.run(EnvironmentTokenVerifier().verify_token("expected-token"))

    assert result is not None
    assert result.client_id == "chatgpt-stockfish-client"


def test_token_verifier_rejects_missing_or_wrong_token(monkeypatch):
    verifier = EnvironmentTokenVerifier()
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    assert asyncio.run(verifier.verify_token("anything")) is None

    monkeypatch.setenv("MCP_AUTH_TOKEN", "expected-token")
    assert asyncio.run(verifier.verify_token("wrong-token")) is None
