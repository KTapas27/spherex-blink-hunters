#!/usr/bin/env bash
# Publish a deployable copy of Blink Hunters (code + the pre-built demo datasets in cache/) to a new
# public GitHub repo under your account, ready for Render (or any host that builds a Dockerfile).
#
#   bash deploy/github_publish.sh [REPO_NAME]      # default: blink-hunters-app
#
# Signs in with `gh auth login` (you confirm a one-time code on github.com; no token to paste).
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="${1:-blink-hunters-app}"
command -v gh >/dev/null || { echo "Needs the GitHub CLI (gh)"; exit 1; }
n_views=$(ls cache/views/*/manifest.json 2>/dev/null | wc -l | tr -d ' ')
[[ "$n_views" -gt 0 ]] || { echo "cache/ is empty: build the demo targets first"; exit 1; }
if ! gh auth status >/dev/null 2>&1; then
  echo "Sign in to GitHub: open the link shown below and enter the one-time code."
  gh auth login -h github.com -p https -w -s repo
fi
USER_NAME=$(gh api user --jq .login)
STAGE=$(mktemp -d)
cp -r Dockerfile .dockerignore requirements.txt backend frontend scripts cache README.md "$STAGE"/
cp deploy/render.yaml "$STAGE/render.yaml"
find "$STAGE" -name __pycache__ -type d -prune -exec rm -rf {} +
printf '__pycache__/\n*.pyc\n.venv/\n' > "$STAGE/.gitignore"
cd "$STAGE"
git init -q -b main
git add -A
git -c user.name="$USER_NAME" -c user.email="$USER_NAME@users.noreply.github.com" commit -q -m "Blink Hunters with pre-built demo datasets ($n_views views)"
echo "Creating https://github.com/$USER_NAME/$REPO and pushing $(git ls-files | wc -l) files..."
gh auth setup-git >/dev/null 2>&1 || true
gh repo create "$REPO" --public --source . --remote origin --push \
  --description "Blink Hunters: SPHEREx sky time-lapse (NASA Space Apps 2026), deployable with Docker"
echo
echo "Repo:            https://github.com/$USER_NAME/$REPO"
echo "Deploy to Render: https://render.com/deploy?repo=https://github.com/$USER_NAME/$REPO"
rm -rf "$STAGE"
