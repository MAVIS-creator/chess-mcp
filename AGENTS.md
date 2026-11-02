# AGENTS.md

## Mission
Maintain and deploy the Victor Stockfish remote MCP server. It exposes read-only chess-analysis tools backed by Stockfish 19 and is intended for ChatGPT/Codex MCP clients.

## Required behavior
- Before changing OpenAI/ChatGPT/Codex/MCP integration, consult the OpenAI developer docs MCP server when available.
- Prefer current Google Cloud Run documentation before changing deployment flags.
- Keep the MCP endpoint at `/mcp` and use Streamable HTTP / HTTP transport.
- Keep Cloud Run concurrency at 1 unless the engine architecture is changed to a true worker pool.
- Never remove server-side caps on analysis time, MultiPV, depth, or nodes.
- Treat all FENs and move strings as untrusted input and validate them.
- Never commit credentials, service-account JSON keys, API keys, or `.env` files.
- Prefer Workload Identity Federation for GitHub Actions instead of long-lived GCP service account keys.
- Run `ruff check app tests` and `pytest -q` before pushing.

## Default GCP settings
- Service: `victor-stockfish-mcp`
- Region: `us-central1` unless the user chooses another region.
- CPU: 2
- Memory: 2Gi
- Concurrency: 1
- Min instances: 1 for low latency; if cost is more important than latency, change to 0.
- Max instances: 3 to cap cost.

## Connection targets
- Local/remote MCP URL: `https://<cloud-run-service>/mcp`
- Health URL: `https://<cloud-run-service>/health`
- Codex: `codex mcp add victorStockfish --url https://<cloud-run-service>/mcp`
- ChatGPT custom plugin/app: add the same public HTTPS MCP URL where custom MCP is supported.

## Repository policy
Use clear commits, e.g. `feat: add Stockfish MCP tools` or `chore: deploy to Cloud Run`.
