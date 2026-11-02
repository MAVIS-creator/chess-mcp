#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-victor-stockfish-mcp}"
RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-chess-mcp-runtime}"

if [[ -z "$PROJECT_ID" ]]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi
if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo "Set PROJECT_ID or run: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 1
fi

gcloud config set project "$PROJECT_ID"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  iam.googleapis.com

RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUNTIME_SA_NAME" \
    --display-name="Chess MCP runtime"
fi

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/datastore.user" \
  --quiet >/dev/null

# Create the default Firestore Native database only when the project does not already have it.
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  echo "Creating Firestore database in $REGION for persistent player history..."
  gcloud firestore databases create \
    --database="(default)" \
    --location="$REGION" \
    --type=firestore-native \
    --quiet
fi

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --service-account "$RUNTIME_SA" \
  --cpu 2 \
  --cpu-boost \
  --memory 2Gi \
  --concurrency 1 \
  --timeout 30 \
  --min 0 \
  --max 3 \
  --set-env-vars "STOCKFISH_THREADS=2,STOCKFISH_HASH_MB=512,MAX_ANALYSIS_MS=15000,MAX_MULTIPV=8,MAX_DEPTH=40,MAX_NODES=50000000,HISTORY_BACKEND=firestore,GCP_PROJECT_ID=${PROJECT_ID},CONTEXT_NETWORK_TIMEOUT_MS=1200"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo
echo "Cloud Run service: $URL"
echo "MCP endpoint:       $URL/mcp"
echo "Health endpoint:    $URL/health"
echo "Player history:     Firestore enabled"
echo
echo "Optional richer master-game opening data: set LICHESS_TOKEN on the Cloud Run service."
