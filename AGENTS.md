# AGENTS.md

## Mission
Maintain and deploy the ChatGPT Stockfish remote chess MCP. The preferred path combines Stockfish 19, opening/master-game context, exact Syzygy tablebases, and bounded Firestore-backed player history for personalized explanations.

## Required behavior
- Before changing OpenAI/ChatGPT/Codex/MCP integration, consult current OpenAI developer docs when available.
- Prefer current Google Cloud Run and Firestore documentation before changing deployment/IAM flags.
- Keep the MCP endpoint at `/mcp` and use HTTP / Streamable HTTP compatible transport.
- Prefer `full_analysis` for ordinary chess questions. Use `adaptive_analysis` when only engine calculation is required.
- Exact Syzygy output is authoritative for supported positions and must override heuristic engine evaluation.
- Player history is advisory context only. It may personalize explanations/training advice but must not override Stockfish or exact tablebase results.
- Keep independent opening/game, tablebase, history, and engine work parallel where possible with short provider timeouts and graceful fallback.
- Keep Cloud Run concurrency at 1 unless the Stockfish architecture becomes a true worker pool.
- Keep Cloud Run minimum instances at 0 by default so personal deployments scale to zero when idle.
- Keep startup CPU boost enabled unless measurement shows it is unnecessary.
- Keep the Cloud Run request timeout at 30 seconds or less. Thirty seconds is a ceiling, not a normal target.
- Keep `full_analysis` default budget below the infrastructure timeout; target ordinary answers in a few seconds.
- Never remove server-side caps on engine time, MultiPV, depth, nodes, history size, or context network timeouts.
- Treat all FENs, moves, player IDs, and notes as untrusted input and validate/bound them.
- Never commit credentials, Lichess tokens, service-account JSON keys, API keys, or `.env` files.
- Lichess Opening Explorer access is optional and authenticated; keep an instant local opening fallback.
- Prefer Workload Identity Federation for GitHub Actions instead of long-lived GCP service-account keys.
- Use a dedicated Cloud Run runtime identity with `roles/datastore.user` for Firestore history.
- Keep repeated-position caches bounded and short-lived. They are latency optimizations, not persistent truth stores.
- Run `ruff check app tests` and `pytest -q` before pushing.

## Default GCP settings
- Service: `victor-stockfish-mcp`
- Region: `us-central1` unless the user chooses another region.
- Runtime service account: `chess-mcp-runtime`
- CPU: 2
- Startup CPU boost: enabled
- Memory: 2Gi
- Concurrency: 1
- Min instances: 0
- Max instances: 3
- Request timeout: 30s
- Firestore: default Native database in the same region when newly created
- History backend: Firestore

## Latency policy
- Quick analysis: target about 0.5–2s engine time.
- Normal analysis: target about 1.2–5s engine time.
- Deep analysis: target about 3–12s engine time.
- `full_analysis` defaults to a 25s budget and is capped below the 30s Cloud Run ceiling.
- Context network calls should usually be capped near 1.2s.
- Never design a normal path that intentionally consumes the full 30s request window.
- Cache repeated Stockfish, opening, and tablebase lookups where safe.
- Do not place giant game databases or Syzygy files in the Cloud Run image; use bounded remote context and compact local fallback data.

## Connection targets
- MCP: `https://<cloud-run-service>/mcp`
- Health: `https://<cloud-run-service>/health`
- Codex: `codex mcp add victorStockfish --url https://<cloud-run-service>/mcp`
- ChatGPT custom MCP/app: use the same HTTPS MCP URL where the account/workspace supports remote custom MCP connections.

## Repository policy
Use clear commits, e.g. `feat: add full chess orchestration`, `perf: cache repeated analysis`, or `chore: deploy to Cloud Run`.
