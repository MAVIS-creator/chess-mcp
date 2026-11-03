from __future__ import annotations

import hmac
import os

import chess
import chess.engine
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.engine import service
from app.server import mcp


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return ""
    return authorization[7:].strip()


def _authorized(request: Request) -> bool:
    expected = os.getenv("MCP_AUTH_TOKEN", "")
    supplied = _bearer_token(request)
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


def _bounded_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


@mcp.custom_route("/api/analyze", methods=["POST"])
async def cedar_analyze(request: Request) -> JSONResponse:
    """Small authenticated REST bridge for the Cedar Chess web client.

    The public browser never receives the Cloud Run bearer token. Cedar's Vercel
    server-side function calls this endpoint and falls back to its local
    Stockfish 19 WASM worker when Cloud Run is unavailable.
    """
    if not _authorized(request):
        return JSONResponse({"error": "Unauthorized."}, status_code=401)

    try:
        payload = await request.json()
    except (ValueError, TypeError):
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "JSON body must be an object."}, status_code=400)

    fen = payload.get("fen")
    if not isinstance(fen, str) or not fen.strip() or len(fen) > 120:
        return JSONResponse({"error": "A valid FEN is required."}, status_code=400)

    time_ms = _bounded_int(payload.get("time_ms"), default=1200, minimum=50, maximum=6000)
    multipv = _bounded_int(payload.get("multipv"), default=3, minimum=1, maximum=5)
    raw_depth = payload.get("depth")
    depth = (
        None
        if raw_depth is None
        else _bounded_int(raw_depth, default=16, minimum=1, maximum=40)
    )

    try:
        result = service.analyze(
            fen.strip(),
            time_ms=time_ms,
            multipv=multipv,
            depth=depth,
        )
        return JSONResponse(result)
    except ValueError:
        return JSONResponse({"error": "Invalid chess position or analysis parameters."}, status_code=400)
    except (OSError, chess.engine.EngineError):
        return JSONResponse({"error": "Engine unavailable."}, status_code=503)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=port,
        path="/mcp",
        stateless_http=True,
        json_response=True,
    )
