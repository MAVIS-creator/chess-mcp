from __future__ import annotations

import hmac
import os

from fastmcp.server.auth import AccessToken, TokenVerifier


class EnvironmentTokenVerifier(TokenVerifier):
    """Validate one bearer token supplied through the runtime secret environment."""

    async def verify_token(self, token: str) -> AccessToken | None:
        expected = os.getenv("MCP_AUTH_TOKEN", "")
        if not expected or not hmac.compare_digest(token, expected):
            return None
        return AccessToken(
            token=token,
            client_id="chatgpt-stockfish-client",
            scopes=["mcp:tools"],
            subject="authorized-client",
        )
