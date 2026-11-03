# Cedar Chess REST bridge

Cedar Chess uses the same deployed Stockfish 19 service as the MCP without exposing the Cloud Run bearer token to browsers.

## Endpoint

`POST /api/analyze`

The endpoint requires the same `Authorization: Bearer ...` value already configured through `MCP_AUTH_TOKEN` for the MCP service. It is intended for server-to-server calls from Cedar Chess's Vercel function, not direct browser access.

Accepted JSON fields:

- `fen` — required chess position
- `time_ms` — clamped to 50–6000 ms
- `multipv` — clamped to 1–5
- `depth` — optional, clamped to 1–40

The route calls the existing shared Stockfish service instance; it does not start a second engine process.

## Cedar fallback behavior

Cedar's Vercel server function calls this endpoint first. If Cloud Run is unavailable, unconfigured, times out, or rejects the request, the browser automatically falls back to Cedar's bundled Stockfish 19 lite-single WASM worker.

The browser never receives `MCP_AUTH_TOKEN`.
