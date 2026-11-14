#!/usr/bin/env bash
# Check a deployed Blink Hunters site: health, and that each demo target is served from baked-in data.
#   bash deploy/verify.sh https://your-site
URL="${1:?usage: $0 SITE_URL}"; URL="${URL%/}"
echo "Health: $(curl -fsS "$URL/api/health" || echo 'not answering')"
for q in "Barnard's Star" "eps Ind B" "WISE J085510.83-071442.5" "RW Aur" "R Dra"; do
  body=$(python3 -c 'import json,sys; print(json.dumps({"q": sys.argv[1], "fov": 0.1, "per_group": 6}))' "$q")
  status=$(curl -fsS -X POST "$URL/api/views" -H 'Content-Type: application/json' --data-binary "$body" |
           python3 -c 'import json,sys; j=json.load(sys.stdin); print(j["status"], "-", j.get("message", ""))' 2>/dev/null || echo "no answer")
  printf '  %-28s %s\n' "$q" "$status"
done
echo "Share a view: $URL/#q=Barnard%27s%20Star&det=6&mode=diff"
