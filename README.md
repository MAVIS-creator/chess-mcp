# Victor Stockfish MCP

A remote MCP server that gives ChatGPT, Codex, and other MCP clients direct access to **Stockfish 19** chess calculation.

## What it exposes

- `validate_position(fen)` — validates FEN and returns legal moves.
- `analyze_position(fen, time_ms, multipv, depth, nodes)` — ranked Stockfish lines.
- `compare_moves(fen, moves, time_ms)` — compares user/model candidate moves.
- `analyze_move(fen, move, time_ms)` — audits one move versus Stockfish's best.
- `tactical_scan(fen, time_ms, multipv, mode)` — deeper MultiPV scan plus tactical signals.
- `engine_status()` — engine version/config/limits.

The MCP endpoint is `/mcp`; the health endpoint is `/health`.

## Architecture

```text
User -> ChatGPT/Codex -> HTTPS MCP -> Cloud Run -> Stockfish 19 -> structured lines -> model explanation
```

Cloud Run is intentionally configured with request concurrency `1` because each container owns one Stockfish process. Autoscaling creates additional containers when necessary.

## Requirements

- Python 3.11+ for local development.
- Docker for the easiest local test.
- Google Cloud CLI (`gcloud`) for deployment.
- A Google Cloud project with billing enabled.
- Git/GitHub CLI if you want Codex to create/push the GitHub repository automatically.

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
docker build -t victor-stockfish-mcp .
docker run --rm -p 8080:8080 --cpus=2 --memory=2g victor-stockfish-mcp
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
CPU                 2 vCPU
Memory              2 GiB
Cloud Run concurrency 1
Min instances       1
Max instances       3
Timeout              60s
Stockfish Threads    2
Stockfish Hash       512 MB
Max engine search    15s per tool call
```

`min=1` makes the service feel much more immediate by keeping one instance warm, but it costs money while idle. Set min instances to `0` if low cost matters more than cold-start latency.

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
4. Model calls `analyze_position`, usually 1–3 seconds and MultiPV 3–5.
5. If candidate moves are close, model calls `compare_moves` or re-runs a deeper search.
6. Model explains the engine lines in human terms.

## Security and cost warning

The starter deployment uses `--allow-unauthenticated` because it is the simplest way for a remote MCP client to reach Cloud Run. The tools are read-only and only analyze chess positions, but **a public endpoint can still be abused to consume CPU and create GCP charges**.

Mitigations already included:

- max 15-second analysis calls
- max MultiPV 8
- max depth 40
- max nodes 50M
- max Cloud Run instances 3
- Cloud Run concurrency 1

For a serious/private deployment, add compatible MCP authentication (OAuth or bearer-token based, depending on client support), quotas/rate limiting, and monitoring. Do not place credentials in tool descriptions, GitHub, or container images.

## GitHub CI/CD

`ci.yml` runs lint/tests on push and PR.

`deploy-cloud-run.yml` deploys `main` to Cloud Run using Google Workload Identity Federation. It expects:

- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

Prefer Workload Identity Federation over a long-lived service-account JSON key. After the GitHub repo exists, Codex can run:

```bash
PROJECT_ID=YOUR_PROJECT_ID GITHUB_REPO=OWNER/victor-stockfish-mcp ./scripts/setup_github_wif.sh
```

The script creates/reuses a GitHub OIDC workload-identity pool/provider, creates a dedicated deployer service account, grants the source-deploy roles, and writes the three GitHub Actions secrets when `gh` is authenticated.

## Let Codex finish the setup for you

Open this repository in Codex and give it the instructions in [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md). The handoff explicitly tells Codex to:

- verify the code
- install/configure `gcloud` if needed
- log into GCP when human authorization is required
- enable APIs
- deploy Cloud Run
- verify the live MCP server
- create/push the GitHub repo
- configure GitHub Actions with Workload Identity Federation where permissions allow
- add the MCP server to Codex
- report the exact URLs and anything that still requires a manual ChatGPT UI step

## Example request after connection

> Analyze this FEN. Start with a 1.5-second MultiPV 5 search. If the top two moves are within 0.20, compare them with a 5-second search and explain the practical difference.

That lets the model orchestrate Stockfish rather than blindly echoing one engine move.
