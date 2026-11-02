# Codex handoff — build, deploy, connect, and push ChatGPT Stockfish MCP

Copy the prompt below into Codex from the root of this repository.

---

You are responsible for taking this repository from local source to a working remote Stockfish MCP server on Google Cloud Run and then pushing the finished project to GitHub.

Work autonomously as far as permissions allow. Do not invent credentials. If an interactive login/authorization page is required, stop only for that human authorization step, then continue automatically.

## 1. Inspect and verify
1. Read `AGENTS.md`, `README.md`, `pyproject.toml`, `Dockerfile`, `app/server.py`, `app/engine.py`, and the workflows.
2. Add the official OpenAI developer-docs MCP to Codex if it is not already configured:
   `codex mcp add openaiDeveloperDocs --url https://developers.openai.com/mcp`
3. Use current official OpenAI/MCP and Google Cloud Run docs to verify any command whose syntax may have changed.
4. Do not downgrade Stockfish below the pinned stable release unless the build proves incompatible.

## 2. Local validation
1. Ensure Python 3.11+ is available; prefer Python 3.12.
2. Create a virtual environment and install `.[dev]`.
3. Run:
   - `ruff check app tests`
   - `pytest -q`
4. If Docker is installed, build the image and run it locally on port 8080.
5. Verify `/health` and use MCP Inspector or `scripts/test_remote.py` against `http://localhost:8080/mcp`.
6. Fix any code/build issue you encounter and rerun tests.

## 3. Google Cloud setup
1. Verify `gcloud` exists. If not, install the official Google Cloud CLI using the supported method for this OS.
2. Run `gcloud auth login` if no usable user session exists. This may require human browser authorization.
3. Determine the intended GCP project. If none is configured and there is exactly one obvious project available to the signed-in user, use it. Otherwise ask only for the project ID.
4. Configure the project and region (`us-central1` by default unless there is a clear reason to use another region).
5. Enable at least:
   - Cloud Run API
   - Cloud Build API
   - Artifact Registry API
6. Deploy using `scripts/deploy_gcp.sh` or equivalent current `gcloud run deploy --source .` commands.
7. Keep these safety/performance defaults unless the user explicitly changes them:
   - 2 vCPU
   - 2 GiB RAM
   - concurrency 1
   - min instances 0 so the service can scale to zero when idle
   - max instances 3
   - timeout 60s
   - Stockfish threads 2
   - Stockfish hash 512 MB
   - max analysis time 15s
8. Public unauthenticated invocation is acceptable for this first read-only chess-analysis deployment, but clearly report that this can be abused and create GCP cost. Do not expose any secrets. If the user wants stronger security, implement OAuth/bearer-token protection compatible with the chosen MCP client instead of relying on obscurity.
9. Capture the deployed service URL and verify:
   - `GET <URL>/health`
   - MCP initialize/tool listing at `<URL>/mcp`
   - a real `adaptive_analysis` call
   - a real `analyze_position` call

## 4. GitHub repository
1. Check whether this directory already has a remote.
2. If it does not, use GitHub CLI (`gh`) if available. Authenticate with `gh auth login` if needed.
3. Use the already-established repository name when one exists; otherwise create `chess-mcp` under the user's authenticated GitHub account.
4. Default visibility: PRIVATE unless the user has already explicitly said public.
5. Initialize git if needed, commit all safe files, and push `main`.
6. Never commit `.env`, GCP credential JSON, access tokens, or other secrets.

## 5. GitHub Actions → GCP
Configure secure continuous deployment with Google Workload Identity Federation if account permissions allow it. Prefer the included `scripts/setup_github_wif.sh` after the GitHub repository exists; inspect it first, then run it with `PROJECT_ID` and `GITHUB_REPO=owner/repo`.

Required GitHub repository secrets/variables for the included workflow:
- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

Prefer WIF over creating/downloading a long-lived service-account JSON key. Grant the deployment service account only the roles actually required for source deployment to Cloud Run and Artifact Registry/Cloud Build usage. If organization policy prevents this setup, leave CI enabled and document exactly which remaining permissions/settings the user must add.

After configuring WIF, trigger the workflow once and verify it succeeds.

## 6. Connect clients
After deployment, output the exact MCP URL.

For Codex, run or instruct:
`codex mcp add victorStockfish --url https://<service>.run.app/mcp`
then verify with:
`codex mcp list`

For ChatGPT, explain that the same MCP URL should be added as a custom MCP/plugin connection in a ChatGPT workspace/account that currently supports custom remote MCP connections. Do not claim the feature exists for an account without checking current OpenAI documentation/account UI.

## 7. Final verification report
Return:
- GitHub repo URL
- Cloud Run service URL
- MCP URL
- health-check status
- Stockfish version returned by `engine_status`
- test results
- CI/CD status
- whether Codex MCP connection was added
- whether ChatGPT connection still needs a manual account/UI step
- estimated cost-sensitive settings (min/max instances, CPU, memory)
- any permissions or login steps that could not be completed

Do not stop after generating commands; execute everything you are permitted to execute and verify the live service.

---
