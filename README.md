# ChatGPT Stockfish MCP

A remote MCP server that gives ChatGPT, Codex, and other MCP clients direct access to **Stockfish 19** chess calculation.

## What it exposes

- `validate_position(fen)` — validates FEN and returns legal moves.
- `analyze_position(fen, time_ms, multipv, depth, nodes)` — fixed-budget ranked Stockfish lines.
- `adaptive_analysis(fen, profile, close_gap_cp)` — starts cheaply and deepens only when the top moves are close.
- `compare_moves(fen, moves, time_ms)` — compares specific candidates in one restricted MultiPV search.
- `analyze_move(fen, move, time_ms)` — audits one move versus Stockfish's best.
- `tactical_scan(fen, time_ms, multipv, mode)` — deeper MultiPV scan plus tactical signals.
- `engine_status()` — engine version/config/profiles/limits.

The MCP endpoint is `/mcp`; the health endpoint is `/health`.

## Architecture

```text
User -> ChatGPT/Codex -> HTTPS MCP -> Cloud Run -> Stockfish 19 -> structured lines -> model explanation
```

Cloud Run is intentionally configured with request concurrency `1` because each container owns one Stockfish process. Autoscaling creates additional containers when necessary.

## Latency target

The service is tuned so **30 seconds is a hard infrastructure ceiling, not a normal response target**.

Typical engine-side targets are:

```text
quick    ~0.5-2s
normal   ~1.2-5s
deep     ~3-12s
hard Cloud Run request ceiling: 30s
```

Cloud Run uses `min=0` to avoid idle spend and enables startup CPU boost to reduce cold-start latency. With 2 configured vCPUs, Cloud Run can temporarily provide extra startup CPU while the container starts. A cold request may still be slower than a warm one, so end-to-end ChatGPT latency cannot be guaranteed exactly, but the MCP itself is deliberately budgeted well below 30 seconds.

## Planned full chess-brain pipeline

The long-term orchestration target is:

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
          |       adaptive_analysis     |
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

Independent lookups should run **in parallel**, not serially. A future orchestration layer should reserve a few seconds of the 30-second ceiling for network/model overhead and cancel optional lookups when their deadline expires. Tablebase results, when available, are exact and should override heuristic engine evaluation for that endgame position.

For low latency, avoid putting huge game or Syzygy datasets directly in the Cloud Run image. Prefer a compact local opening index/cache plus bounded remote/storage lookups, with aggressive caching of repeated FENs.

## How the adaptive analysis works

For ordinary analysis, prefer `adaptive_analysis` instead of immediately asking for a long fixed search.

Profiles:

```text
quick   initial 0.5s, confirmation 1.5s, MultiPV 2
normal  initial 1.2s, confirmation 3.5s, MultiPV 4
deep    initial 3.0s, confirmation 8.0s, MultiPV 5
```

The first pass checks several candidate moves. If the top two are within the configured centipawn gap (35 cp by default) and no forced mate is already visible, the MCP runs a deeper search restricted to those two moves. Obvious positions therefore stay cheap, while unclear positions get extra calculation.

This is not online learning. Stockfish uses its shipped NNUE evaluation network plus search; it does not permanently learn from each request or from your games while this service is running. If we later want personalization, keep player/game history outside Stockfish and retrieve it as context alongside objective engine calculation.

## Requirements

- Python 3.11+ for local development.
- Docker for the easiest local test.
- Google Cloud CLI (`gcloud`) for deployment.
- A Google Cloud project with billing enabled.
- Git/GitHub CLI if you want Codex to configure deployment automatically.

## Local Python development

Install a local Stockfish binary and point `STOCKFISH_PATH` at it.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -e '.[dev]'
export STOCKFISH_PATH=/path/to/stockfish
ruff check app tests
pytest -q
python -m app.server
```

MCP: `http://localhost:8080/mcp`

Health: `http://localhost:8080/health`

## Docker local test

The Docker build compiles the pinned stable Stockfish release from the official source repo.

```bash
docker build -t chatgpt-stockfish-mcp .
docker run --rm -p 8080:8080 --cpus=2 --memory=2g chatgpt-stockfish-mcp
```

Then:

```bash
curl http://localhost:8080/health
python scripts/test_remote.py http://localhost:8080/mcp
```

You can also use MCP Inspector and point it at `http://localhost:8080/mcp`.

## Deploy to Google Cloud Run

Authenticate and select a project:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

Then deploy:

```bash
PROJECT_ID=YOUR_PROJECT_ID ./scripts/deploy_gcp.sh
```

The script enables Cloud Run, Cloud Build, and Artifact Registry APIs, then deploys from source.

Default production configuration:

```text
CPU                   2 vCPU
Startup CPU boost     enabled
Memory                2 GiB
Cloud Run concurrency 1
Min instances         0
Max instances         3
Timeout               30s
Stockfish Threads     2
Stockfish Hash        512 MB
Max engine search     15s per fixed tool call
```

`min=0` is intentional for this personal deployment: Cloud Run can scale to zero when idle, minimizing idle cost. Startup CPU boost is enabled to make those cold starts less painful without keeping an instance permanently warm.

After deploy, obtain the URL:

```bash
gcloud run services describe victor-stockfish-mcp \
  --region us-central1 \
  --format='value(status.url)'
```

Your MCP URL is:

```text
https://YOUR-CLOUD-RUN-URL/mcp
```

## Connect Codex directly

```bash
codex mcp add victorStockfish --url https://YOUR-CLOUD-RUN-URL/mcp
codex mcp list
```

For current OpenAI documentation inside Codex, it is useful to add:

```bash
codex mcp add openaiDeveloperDocs --url https://developers.openai.com/mcp
```

## Connect ChatGPT

Use the same public HTTPS MCP endpoint when adding a custom MCP/plugin connection in a ChatGPT account/workspace that currently supports custom remote MCP servers.

```text
https://YOUR-CLOUD-RUN-URL/mcp
```

Availability and the exact ChatGPT UI can vary by plan/workspace, so verify the current OpenAI documentation/account UI rather than assuming the option is present.

Once connected, a normal flow is:

1. User sends a position or chess-board screenshot.
2. Model converts the board to FEN.
3. Model calls `validate_position`.
4. Model calls `adaptive_analysis` with `normal` for ordinary positions.
5. If the question is specifically about candidate moves, model calls `compare_moves`.
6. Model explains the engine lines in human terms.

## Security and cost warning

The starter deployment uses `--allow-unauthenticated` because it is the simplest way for a remote MCP client to reach Cloud Run. The tools are read-only and only analyze chess positions, but **a public endpoint can still be abused to consume CPU and create GCP charges**.

Mitigations already included:

- scale to zero when idle (`min instances = 0`)
- Cloud Run request timeout 30 seconds
- max 15-second engine searches
- max MultiPV 8
- max depth 40
- max nodes 50M
- max Cloud Run instances 3
- Cloud Run concurrency 1
- adaptive analysis that only deepens when needed

For a serious/private deployment, add compatible MCP authentication (OAuth or bearer-token based, depending on client support), quotas/rate limiting, and monitoring. Do not place credentials in tool descriptions, GitHub, or container images.

## GitHub CI/CD

`ci.yml` runs lint/tests on push and PR.

`deploy-cloud-run.yml` deploys `main` to Cloud Run using Google Workload Identity Federation. It expects:

- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

Prefer Workload Identity Federation over a long-lived service-account JSON key. After the GitHub repo exists, Codex can run:

```bash
PROJECT_ID=YOUR_PROJECT_ID GITHUB_REPO=MAVIS-creator/chess-mcp ./scripts/setup_github_wif.sh
```

The script creates/reuses a GitHub OIDC workload-identity pool/provider, creates a dedicated deployer service account, grants the source-deploy roles, and writes the three GitHub Actions secrets when `gh` is authenticated.

## Example request after connection

> Analyze this FEN with the normal adaptive profile. If the top moves are close, confirm them more deeply and explain the practical difference.

That lets the model orchestrate Stockfish instead of blindly echoing one engine move.
