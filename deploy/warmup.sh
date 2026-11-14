#!/usr/bin/env bash
# Ask a deployed Blink Hunters instance to build the 5 challenge targets, so judges never wait.
# Builds each preset at the UI default (6 exposures/visit/detector) and with every exposure
# (needed to see WISE 0855). From a US region this takes a few minutes in total.
#
# Usage:  deploy/warmup.sh https://blink-hunters-xxxxx.us-east1.run.app
#
# Cloud Run keeps these on the instance's in-memory disk: deploy with MIN_INSTANCES=1 so they
# survive, or bake a pre-built cache/ into the image instead.
set -euo pipefail
URL="${1:?usage: $0 SERVICE_URL}"
URL="${URL%/}"

QUERIES=("Barnard's Star" "eps Ind B" "WISE J085510.83-071442.5" "RW Aur" "R Dra")

start() {  # $1 query, $2 per_group -> prints view key
  python3 -c 'import json,sys; print(json.dumps({"q": sys.argv[1], "fov": 0.1, "per_group": int(sys.argv[2])}))' "$1" "$2" |
    curl -fsS -X POST "$URL/api/views" -H 'Content-Type: application/json' --data-binary @- |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])'
}

for per_group in 6 0; do
  for q in "${QUERIES[@]}"; do
    key=$(start "$q" "$per_group")
    printf '%-28s per_group=%s key=%s ' "$q" "$per_group" "$key"
    while :; do
      status=$(curl -fsS "$URL/api/views/$key" | python3 -c 'import json,sys; j=json.load(sys.stdin); print(j["status"], j.get("done",""), j.get("total",""))')
      case "$status" in
        done*)  echo "done"; break ;;
        error*) echo "ERROR: $(curl -fsS "$URL/api/views/$key" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("message"))')"; break ;;
        *)      printf '.'; sleep 5 ;;
      esac
    done
  done
done
echo "Cached views: $(curl -fsS "$URL/api/health")"
