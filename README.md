# ChatGPT Stockfish MCP

A low-latency remote chess MCP for ChatGPT, Codex, and other MCP clients. It combines **Stockfish 19**, opening/master-game context, exact Syzygy tablebases, and optional persistent player history.

## Implemented architecture

```text
                    Chess request
                         |
                         v
                  ChatGPT / model
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
   Opening/Game DB    Stockfish      Player history
          |              |              |
          |              v              |
          |       adaptive analysis     |
          |              |              |
          +--------------+--------------+
                         |
                         v
                 Syzygy tablebase
                         |
                         v
                   Model reasoning
                         |
                         v
                Final recommendation
```

The independent context lookups start in parallel while Stockfish searches. Exact Syzygy results are authoritative in supported endgames. Player history is advisory only: it personalizes explanations and training advice but never overrides objective calculation.

## MCP tools

- `full_analysis(...)` — preferred tool; runs the whole parallel chess-brain pipeline.
- `validate_position(fen)` — validates FEN and returns legal moves.
- `adaptive_analysis(fen, profile, close_gap_cp)` — Stockfish only, with selective deepening.
- `analyze_position(...)` — fixed-budget Stockfish analysis.
- `opening_context(fen)` — local opening recognition plus optional authenticated Lichess master-game data.
- `tablebase_lookup(fen)` — exact Lichess Syzygy lookup for supported <=7-piece positions.
- `player_history(player_id, fen)` — reads persistent personal history when Firestore is enabled.
- `record_player_event(...)` — stores a bounded training/history event in Firestore.
- `compare_moves(...)` — compares named candidates in one restricted MultiPV search.
- `analyze_move(...)` — audits one move against Stockfish's best.
- `tactical_scan(...)` — MultiPV tactical scan and forcing signals.
- `engine_status()` — engine, cache, context, and safety configuration.

MCP endpoint: `/mcp`

Health endpoint: `/health`

## Latency target

**30 seconds is the infrastructure ceiling, not the target.**

```text
quick     usually ~0.5-2s engine time
normal    usually ~1.2-5s engine time
deep      usually ~3-12s engine time
full_analysis default budget: 25s
Cloud Run request timeout: 30s
```

`full_analysis` starts opening/game lookup, tablebase lookup, and player-history lookup concurrently. Stockfish searches at the same time. Optional network context is individually bounded to about 1.2 seconds so a slow provider cannot hold the answer hostage.

Repeated identical Stockfish requests are cached for a short period on warm Cloud Run instances. Opening and tablebase results have separate TTL caches.

## Stockfish behavior

Stockfish itself does **not** learn online from requests. It uses its shipped NNUE network plus search. The learning/personalization layer lives outside the engine in player history.

Adaptive profiles:

```text
quick   initial 0.5s, confirmation 1.5s, MultiPV 2
normal  initial 1.2s, confirmation 3.5s, MultiPV 4
deep    initial 3.0s, confirmation 8.0s, MultiPV 5
```

If the top moves are already clearly separated, no confirmation search is needed. If they are close, only the top candidates are re-searched more deeply. If Syzygy already gives an exact result, the deeper engine confirmation is skipped.

## Opening and game context

A compact local opening index provides instant fallback recognition for common openings.

For richer master-game statistics, configure a Lichess access token as a Cloud Run secret/environment value:

```text
LICHESS_TOKEN=...
```

The remote provider uses the authenticated Lichess Opening Explorer master database. Do not commit the token to GitHub.

## Syzygy

For standard positions with seven or fewer pieces, the MCP queries the Lichess tablebase service. When the response is exact, `full_analysis` marks Syzygy as the authoritative source and returns its best tablebase move/result instead of treating Stockfish's heuristic score as final.

## Persistent player history

The GCP deployment script creates/reuses a dedicated runtime service account and a Firestore Native database. The service account receives `roles/datastore.user` so it can read and write only the configured chess history data allowed by project IAM.

History is bounded per player (`HISTORY_MAX_EVENTS`, default 80) so one document does not grow forever.

Example event fields include:

```text
position
played move
best move
centipawn loss
outcome
short note
recorded time
```

This allows future analysis to say things such as: "Objectively Nf5 is best; you have misplayed this structure before by exchanging that knight too early."

## GCP defaults

```text
Cloud Run CPU          2 vCPU
Startup CPU boost      enabled
Memory                 2 GiB
Concurrency            1
Min instances          0
Max instances          3
Request timeout        30s
Stockfish threads      2
Stockfish hash         512 MB
Max fixed engine call  15s
Engine cache TTL       180s
Context network cap    1200ms
History backend        Firestore
```

`min=0` keeps idle cost low. Startup CPU boost reduces cold-start pain without paying for a permanently warm instance.

## Deploy

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
PROJECT_ID=YOUR_PROJECT_ID ./scripts/deploy_gcp.sh
```

The deployment script enables Cloud Run, Cloud Build, Artifact Registry, IAM, and Firestore APIs; creates/reuses the runtime identity; creates the default Firestore database if needed; grants the runtime Firestore data role; and deploys the service.

After deployment:

```bash
gcloud run services describe victor-stockfish-mcp \
  --region us-central1 \
  --format='value(status.url)'
```

Then verify:

```bash
curl https://YOUR-SERVICE.run.app/health
python scripts/test_remote.py https://YOUR-SERVICE.run.app/mcp
```

## GitHub Actions -> GCP

Run after the initial GCP setup:

```bash
PROJECT_ID=YOUR_PROJECT_ID \
GITHUB_REPO=MAVIS-creator/chess-mcp \
./scripts/setup_github_wif.sh
```

This configures Workload Identity Federation instead of a long-lived JSON key and grants the GitHub deployer permission to deploy revisions under the dedicated chess runtime identity.

The workflow expects:

- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

## Connect an MCP client

Codex:

```bash
codex mcp add victorStockfish --url https://YOUR-SERVICE.run.app/mcp
codex mcp list
```

Use the same public HTTPS MCP URL in a ChatGPT workspace/account that supports custom remote MCP connections.

## Local validation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ruff check app tests
pytest -q
```

For a real local engine test, set `STOCKFISH_PATH` to a Stockfish binary or build/run the provided Docker image.

## Security and fair-play notes

The starter Cloud Run endpoint is public so remote MCP clients can reach it. CPU/search limits, max instances, caching, and scale-to-zero reduce risk, but a public compute endpoint can still be abused; add compatible MCP authentication/rate limiting before broader use.

Do not use engine assistance during live games on platforms whose fair-play rules forbid it. This project is intended for analysis, study, training, and allowed use cases.
