#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-}"
GITHUB_REPO="${GITHUB_REPO:-}"   # owner/repo
POOL_ID="${POOL_ID:-github}"
PROVIDER_ID="${PROVIDER_ID:-github-provider}"
DEPLOYER_SA_NAME="${DEPLOYER_SA_NAME:-github-cloud-run-deployer}"
RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-chess-mcp-runtime}"

if [[ -z "$PROJECT_ID" ]]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi
if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo "Set PROJECT_ID or configure gcloud project first." >&2
  exit 1
fi
if [[ -z "$GITHUB_REPO" || "$GITHUB_REPO" != */* ]]; then
  echo "Set GITHUB_REPO=owner/repo" >&2
  exit 1
fi

gcloud config set project "$PROJECT_ID"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
DEPLOYER_SA="${DEPLOYER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

if ! gcloud iam service-accounts describe "$DEPLOYER_SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$DEPLOYER_SA_NAME" \
    --display-name="GitHub Cloud Run deployer"
fi
if ! gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUNTIME_SA_NAME" \
    --display-name="Chess MCP runtime"
fi

for ROLE in roles/run.sourceDeveloper roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOYER_SA}" \
    --role="$ROLE" \
    --quiet >/dev/null
done

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/datastore.user" \
  --quiet >/dev/null

# Let GitHub deploy Cloud Run revisions under the dedicated runtime identity.
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:${DEPLOYER_SA}" \
  --role="roles/iam.serviceAccountUser" \
  --quiet >/dev/null

# Let the source-build service account build the container image.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/run.builder" \
  --quiet >/dev/null

if ! gcloud iam workload-identity-pools describe "$POOL_ID" \
    --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL_ID" \
    --location=global \
    --display-name="GitHub Actions"
fi

if ! gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
    --location=global \
    --workload-identity-pool="$POOL_ID" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --location=global \
    --workload-identity-pool="$POOL_ID" \
    --display-name="GitHub Actions provider" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'"
fi

PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_REPO}"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --member="$PRINCIPAL" \
  --role="roles/iam.workloadIdentityUser" \
  --quiet >/dev/null

PROVIDER_NAME="$(gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
  --location=global \
  --workload-identity-pool="$POOL_ID" \
  --format='value(name)')"

cat <<EOF
WIF configured.
GCP_PROJECT_ID=$PROJECT_ID
GCP_WORKLOAD_IDENTITY_PROVIDER=$PROVIDER_NAME
GCP_SERVICE_ACCOUNT=$DEPLOYER_SA
GCP_RUNTIME_SERVICE_ACCOUNT=$RUNTIME_SA
EOF

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1 && \
  gh secret set GCP_PROJECT_ID --repo "$GITHUB_REPO" --body "$PROJECT_ID" && \
  gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "$GITHUB_REPO" --body "$PROVIDER_NAME" && \
  gh secret set GCP_SERVICE_ACCOUNT --repo "$GITHUB_REPO" --body "$DEPLOYER_SA"; then
  echo "GitHub Actions secrets were set on $GITHUB_REPO."
else
  echo "GitHub Actions secrets could not be set; use the identifiers above as repository secrets or workflow configuration."
fi
