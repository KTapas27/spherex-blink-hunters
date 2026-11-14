#!/usr/bin/env bash
# Deploy Blink Hunters to a free Hugging Face Space (Docker), with the demo datasets in cache/ baked in.
#
#   bash deploy/huggingface_deploy.sh [SPACE_NAME]        # default: blink-hunters
#
# Needs a free huggingface.co account and a token with WRITE access
# (https://huggingface.co/settings/tokens). If you are not logged in, the script asks you to paste
# the token; it is not shown on screen and is only saved in Hugging Face's own login file.
# Build cache/ first (deploy/cloudshell_deploy.sh steps 1-2, or scripts/precache.py).
set -euo pipefail
cd "$(dirname "$0")/.."
SPACE="${1:-blink-hunters}"
PY=.venv/bin/python
[[ -x $PY ]] || { python3 -m venv .venv; }
$PY -m pip install -q "huggingface_hub>=0.25"

n_views=$(ls cache/views/*/manifest.json 2>/dev/null | wc -l | tr -d ' ')
echo "Datasets to include: $n_views views, $(du -sh cache | cut -f1), $(find cache -type f | wc -l) files"
[[ "$n_views" -gt 0 ]] || { echo "cache/ is empty: build the demo targets first (scripts/precache.py)"; exit 1; }

if ! $PY -c "from huggingface_hub import whoami; whoami()" >/dev/null 2>&1; then
  echo
  read -r -s -p "Paste your Hugging Face WRITE token (hidden) and press Enter: " HF_TOKEN; echo
  $PY -c "import sys; from huggingface_hub import login; login(token=sys.argv[1], add_to_git_credential=False)" "$HF_TOKEN" >/dev/null
  unset HF_TOKEN
fi

STAGE=$(mktemp -d)
cp -r Dockerfile .dockerignore requirements.txt backend frontend scripts cache "$STAGE"/
cp deploy/hf_space_README.md "$STAGE/README.md"
find "$STAGE" -name __pycache__ -type d -prune -exec rm -rf {} +

$PY - "$STAGE" "$SPACE" <<'PYEOF'
import sys, time, subprocess
from huggingface_hub import HfApi
stage, space = sys.argv[1], sys.argv[2]
api = HfApi()
user = api.whoami()["name"]
repo = f"{user}/{space}"
api.create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True)
print(f"Uploading to https://huggingface.co/spaces/{repo} ...", flush=True)
api.upload_folder(folder_path=stage, repo_id=repo, repo_type="space",
                  commit_message="Deploy Blink Hunters with pre-built demo datasets")
host = getattr(api.space_info(repo), "host", None) or f"https://{repo.lower().replace('/', '-').replace('_', '-').replace('.', '-')}.hf.space"
print("Hugging Face is building the app (usually 5-10 minutes)...", flush=True)
last = None
for _ in range(120):  # up to 30 min
    stage_now = api.get_space_runtime(repo).stage
    if stage_now != last:
        print(f"  {time.strftime('%H:%M:%S')} {stage_now}", flush=True)
        last = stage_now
    if stage_now in ("RUNNING",):
        break
    if stage_now in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"):
        print(f"Build failed: see the logs at https://huggingface.co/spaces/{repo}?logs=build")
        sys.exit(1)
    time.sleep(15)
print(f"\nPublic link: {host}")
time.sleep(10)
subprocess.run(["bash", "deploy/verify.sh", host])
PYEOF
rm -rf "$STAGE"
