# Codex handoff — deploy and verify the complete ChatGPT Stockfish MCP

You are responsible for taking this repository from source to a working remote chess MCP on Google Cloud Run, with the complete implemented pipeline: Stockfish 19 + opening/master-game context + Syzygy + persistent Firestore player history.

Work autonomously as far as permissions allow. Do not invent credentials. Stop only for required human login/authorization, then continue.

## 1. Inspect and verify
1. Read `AGENTS.md`, `README.md`, `pyproject.toml`, `Dockerfile`, `app/server.py`, `app/engine.py`, `app/context.py`, `app/orchestrator.py`, deployment scripts, and workflows.
2. Use current official OpenAI/MCP, Google Cloud Run, Firestore, and Lichess API docs when syntax or behavior may have changed.
3. Do not downgrade Stockfish below the pinned stable release unless the build proves incompatible.
4. Preserve the 30-second infrastructure ceiling and the normal few-seconds latency goal.

## 2. Local validation
1. Use Python 3.12 where available.
2. Create a virtual environment and install `.[dev]`.
3. Run:
   - `ruff check app tests`
   - `pytest -q`
4. If Docker is available, build and run the image locally.
5. Verify `/health`, MCP tool listing, `full_analysis`, `adaptive_analysis`, and `tablebase_lookup` using `scripts/test_remote.py` or MCP Inspector.
6. Fix any issue encountered and rerun validation.

## 3. Google Cloud setup
1. Verify/install `gcloud` using the official method.
2. Authenticate with `gcloud auth login` when required.
3. Select the intended project and use `us-central1` unless the user explicitly chooses another region.
4. Run `scripts/deploy_gcp.sh` as the preferred setup path. It should:
   - enable Cloud Run, Cloud Build, Artifact Registry, IAM, and Firestore APIs
   - create/reuse `chess-mcp-runtime@PROJECT_ID.iam.gserviceaccount.com`
   - grant that runtime identity `roles/datastore.user`
   - create the default Firestore Native database when one does not exist
   - deploy the Cloud Run service under the dedicated runtime identity
5. Preserve these defaults unless explicitly changed:
   - 2 vCPU
   - startup CPU boost enabled
   - 2 GiB RAM
   - concurrency 1
   - min instances 0
   - max instances 3
   - request timeout 30s
   - Stockfish threads 2
   - Stockfish hash 512 MB
   - max fixed engine call 15s
   - context provider timeout around 1200ms
   - Firestore history enabled
6. Treat 30 seconds as a hard ceiling, not a target. `full_analysis` should normally finish much sooner.
7. Do not put credentials or Lichess tokens in GitHub or the image.

## 4. Optional Lichess master-game enrichment
The MCP always has a fast local opening fallback. Richer master-game opening statistics require an authenticated Lichess Opening Explorer token.

If the user has/provides a Lichess token, store it as a Cloud Run secret or protected environment value named `LICHESS_TOKEN`. Never commit it. If no token is available, leave the remote opening explorer disabled; `full_analysis` must still work using the local fallback.

## 5. Verify the live chess brain
After deployment, capture the Cloud Run URL and verify all of the following:
1. `GET <URL>/health` returns healthy Stockfish status and shows history enabled.
2. MCP initialize/tool listing works at `<URL>/mcp`.
3. `engine_status` returns Stockfish identity, cache configuration, and context status.
4. `full_analysis` on the starting position returns within its budget and includes:
   - engine result
   - opening/game context
   - tablebase applicability result
   - player-history section
5. `tablebase_lookup` on a valid <=7-piece position returns an exact Syzygy result when supported.
6. `record_player_event` stores a test event for a temporary player ID, then `player_history` can read it back. Remove/ignore the temporary test data afterward if practical.
7. Repeating an identical Stockfish request on the same warm instance should show the engine cache being used where applicable.

## 6. GitHub Actions -> GCP
Run/inspect `scripts/setup_github_wif.sh` with:

```bash
PROJECT_ID=YOUR_PROJECT_ID GITHUB_REPO=MAVIS-creator/chess-mcp ./scripts/setup_github_wif.sh
```

It should configure Workload Identity Federation, create/reuse the GitHub deployer and chess runtime identities, grant the runtime Firestore data role, and allow the deployer to act as the runtime service account.

Required GitHub secrets:
- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

Trigger the deploy workflow once after setup and verify it succeeds.

## 7. Connect clients
For Codex:

```bash
codex mcp add victorStockfish --url https://<service>.run.app/mcp
codex mcp list
```

For ChatGPT, use the same HTTPS MCP URL in an account/workspace that currently supports remote custom MCP connections. Verify current product documentation/account UI rather than assuming availability.

## 8. Required reasoning rules
- Prefer `full_analysis` for normal user requests.
- Exact Syzygy result overrides Stockfish evaluation in supported endgames.
- Stockfish remains the objective source outside exact tablebase positions.
- Opening/master-game statistics are supporting context, not an engine override.
- Player history is only for personalization/training advice and must not alter the objective best move.
- Independent providers should run in parallel with short timeouts and graceful fallback.
- Never use the entire 30-second window by default.

## 9. Final report
Return:
- GitHub repo and PR/commit status
- Cloud Run service URL
- MCP URL
- health status
- Stockfish version
- `full_analysis` measured latency
- tablebase verification result
- Firestore history read/write verification
- local/CI test results
- GitHub Actions deployment result
- whether Codex MCP was connected
- whether ChatGPT still needs a manual account/UI connection step
- current cost controls (`min=0`, `max=3`, CPU, memory, timeout)
- any login/permission/token step that could not be completed

Do not stop after merely printing commands; execute and verify everything permitted by the current environment.
