#!/usr/bin/env bash
# One-command public deployment, run from Google Cloud Shell (https://shell.cloud.google.com).
#
#   bash deploy/cloudshell_deploy.sh [PROJECT_ID]
#
# 1. installs the Python packages in a local .venv
# 2. builds the 5 demo targets into cache/ exactly as the local app does (6' view, 6 exposures per
#    visit per detector, plus 3' views cut from them, plus every exposure for WISE 0855), with the
#    Gaia overlay, straight from IRSA and the SPHEREx copy on AWS
# 3. deploys to Cloud Run with that cache baked into the image, so the public site shows the same
#    views as localhost instantly, survives restarts, and needs no archive access for the demos
#
# Re-running is safe: finished targets are reused from cache/. Set SKIP_CACHE=1 to deploy
# whatever is in cache/ (e.g. a cache.zip copied from your own PC) without building.
set -uo pipefail
cd "$(dirname "$0")/.."

PROJECT_ID="${1:-${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}}"
if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo "Usage: bash deploy/cloudshell_deploy.sh YOUR_PROJECT_ID   (list them: gcloud projects list)"; exit 1
fi
gcloud config set project "$PROJECT_ID" >/dev/null 2>&1
export PROJECT_ID

step() { printf '\n\033[1;33m== %s ==\033[0m\n' "$*"; }

if [[ "${SKIP_CACHE:-0}" != "1" ]]; then
  step "1/3 Installing Python packages (about 2 minutes, first run only)"
  [[ -x .venv/bin/python ]] || python3 -m venv .venv
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements.txt || { echo "pip install failed"; exit 1; }

  step "2/3 Building the demo datasets into cache/ (about 10-20 minutes)"
  ok=1
  .venv/bin/python scripts/precache.py --fov 0.1 --per-group 6 --gaia || ok=0
  .venv/bin/python scripts/precache.py --fov 0.05 --per-group 6 --gaia || ok=0   # 3' views: cut from the 6' stamps
  .venv/bin/python scripts/precache.py "WISE J085510.83-071442.5" --fov 0.1 --per-group 0 --gaia || ok=0
  if [[ $ok -eq 0 ]]; then
    echo
    echo "Some targets failed (the NASA archive may be busy). Re-run this script in a few minutes:"
    echo "finished targets are kept. To deploy anyway with what is built: SKIP_CACHE=1 bash $0 $PROJECT_ID"
    exit 1
  fi
fi

step "3/3 Deploying to Cloud Run (about 5 minutes)"
echo "Cache to bake in: $(ls cache/views/*/manifest.json 2>/dev/null | wc -l) views, $(du -sh cache | cut -f1)"
bash deploy/cloudrun.sh
