#!/usr/bin/env bash
# Deploy Blink Hunters to Google Cloud Run (built remotely by Cloud Build; no local Docker needed).
#
# Usage (from the project root):
#   deploy/cloudrun.sh                       # uses your current gcloud project
#   PROJECT_ID=my-proj deploy/cloudrun.sh
#   MIN_INSTANCES=1 deploy/cloudrun.sh       # keep one instance warm during judging (small cost)
set -euo pipefail

cd "$(dirname "$0")/.."

SERVICE="${SERVICE:-blink-hunters}"
REGION="${REGION:-us-east1}"          # next to the SPHEREx S3 bucket (AWS us-east-1)
MIN_INSTANCES="${MIN_INSTANCES:-0}"
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"

command -v gcloud >/dev/null || { echo "Install the Google Cloud CLI: https://cloud.google.com/sdk/docs/install"; exit 1; }
if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo "No project set. Run:  gcloud config set project YOUR_PROJECT_ID   (or PROJECT_ID=... $0)"; exit 1
fi
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
  echo "Not logged in. Run:  gcloud auth login"; exit 1
fi

n_views=$(ls cache/views/*/manifest.json 2>/dev/null | wc -l | tr -d ' ')
if [[ "$n_views" -eq 0 ]]; then
  echo "NOTE: no pre-built views in cache/. The image will ship empty; run deploy/warmup.sh after"
  echo "      deploying so Cloud Run builds the 5 demo targets itself (and use MIN_INSTANCES=1 to keep them)."
fi
echo "Project $PROJECT_ID · region $REGION · $n_views pre-built views will be baked in."

echo "Enabling required APIs (first run only takes a minute)..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  --project "$PROJECT_ID"

# Notes on the flags:
#  --max-instances 1      view-building jobs and their progress live in process memory, so all
#                         requests must reach the same instance.
#  --no-cpu-throttling    jobs keep running in a background thread after the HTTP request returns;
#                         with throttling, Cloud Run would freeze them between polls.
#  --memory 2Gi           new targets are cached on the container's in-memory disk.
gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source . \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 2 \
  --memory 2Gi \
  --no-cpu-throttling \
  --cpu-boost \
  --concurrency 80 \
  --timeout 300 \
  --min-instances "$MIN_INSTANCES" \
  --max-instances 1 \
  --quiet

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format "value(status.url)")
echo
echo "Deployed: $URL"
echo "Health:   $(curl -fsS "$URL/api/health" || echo 'not answering yet, retry in a few seconds')"

# Check that every demo target is served from the baked-in data (instant "Ready (cached)").
echo "Checking the demo targets on the live site:"
for q in "Barnard's Star" "eps Ind B" "WISE J085510.83-071442.5" "RW Aur" "R Dra"; do
  body=$(python3 -c 'import json,sys; print(json.dumps({"q": sys.argv[1], "fov": 0.1, "per_group": 6}))' "$q")
  status=$(curl -fsS -X POST "$URL/api/views" -H 'Content-Type: application/json' --data-binary "$body" |
           python3 -c 'import json,sys; j=json.load(sys.stdin); print(j["status"], "-", j.get("message", ""))' 2>/dev/null || echo "no answer")
  printf '  %-28s %s\n' "$q" "$status"
done
echo
echo "Public link: $URL"
echo "Share a view: $URL/#q=Barnard%27s%20Star&det=6&mode=diff"
