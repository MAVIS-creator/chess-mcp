# AGENTS.md

## Mission
Maintain and deploy the ChatGPT Stockfish remote MCP server. It exposes read-only chess-analysis tools backed by Stockfish 19 and is intended for ChatGPT/Codex MCP clients.

## Required behavior
- Before changing OpenAI/ChatGPT/Codex/MCP integration, consult the OpenAI developer docs MCP server when available.
- Prefer current Google Cloud Run documentation before changing deployment flags.
- Keep the MCP endpoint at `/mcp` and use Streamable HTTP / HTTP transport.
- Keep Cloud Run concurrency at 1 unless the engine architecture is changed to a true worker pool.
- Keep Cloud Run minimum instances at 0 by default so the personal deployment can scale to zero when idle.
- Keep startup CPU boost enabled unless measurement shows it is unnecessary.
- Keep the Cloud Run request timeout at 30 seconds or less; 30 seconds is a ceiling, not a normal analysis target.
- Never remove server-side caps on analysis time, MultiPV, depth, or nodes.
- Treat all FENs and move strings as untrusted input and validate them.
- Never commit credentials, service-account JSON keys, API keys, or `.env` files.
- Prefer Workload Identity Federation for GitHub Actions instead of long-lived GCP service account keys.
- Prefer `adaptive_analysis` for ordinary MCP analysis because it deepens only when needed.
- Design future opening/game retrieval, player-history lookup, Stockfish, and tablebase lookup to run independently in parallel where possible, with bounded timeouts and graceful fallback.
- Reserve part of the 30-second end-to-end target for network/model overhead; do not spend the whole budget inside Stockfish.
- Run `ruff check app tests` and `pytest -q` before pushing.

## Default GCP settings
- Service: `victor-stockfish-mcp`
- Region: `us-central1` unless the user chooses another region.
- CPU: 2
- Startup CPU boost: enabled
- Memory: 2Gi
- Concurrency: 1
- Min instances: 0 to minimize idle cost.
- Max instances: 3 to cap cost.
- Request timeout: 30s

## Latency policy
- Quick analysis: target about 0.5–2s engine time.
- Normal analysis: target about 1.2–5s engine time.
- Deep analysis: target about 3–12s engine time.
- Never design a normal path that intentionally consumes the full 30s Cloud Run request window.
- Cache repeated FEN/context lookups where safe and useful.
- Prefer compact local indexes/caches over huge datasets inside the Cloud Run image.

## Connection targets
- Local/remote MCP URL: `https://<cloud-run-service>/mcp`
- Health URL: `https://<cloud-run-service>/health`
- Codex: `codex mcp add victorStockfish --url https://<cloud-run-service>/mcp`
- ChatGPT custom plugin/app: add the same public HTTPS MCP URL where custom MCP is supported.

## Repository policy
Use clear commits, e.g. `feat: add Stockfish MCP tools` or `chore: deploy to Cloud Run`.
