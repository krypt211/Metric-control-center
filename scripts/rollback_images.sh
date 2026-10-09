#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
stamp=${1:?Usage: bash scripts/rollback_images.sh TIMESTAMP}
[[ "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || exit 2
state=".deploy-state/$stamp"
test -f "$state/compose.yml"
echo "Image rollback only. Confirm database compatibility in SERVER_DEPLOYMENT.md."
read -r -p "Type schema-compatible to continue: " answer
test "$answer" = "schema-compatible" || exit 2
python3 - "$state" "$stamp" <<'PY'
import json,sys
state,stamp=sys.argv[1:]
services={s:{"image":f"mcc-rollback-{s}:{stamp}","build":None} for s in ("backend","frontend","worker","scheduler")}
open(state+"/rollback.json","w").write(json.dumps({"services":services}))
PY
docker compose --project-directory "$PWD" --env-file "$state/env" -f "$state/compose.yml" -f "$state/rollback.json" up -d --no-build --no-deps backend frontend worker scheduler
dc=(docker compose --project-directory "$PWD" --env-file "$state/env" -f "$state/compose.yml" -f "$state/rollback.json")
for attempt in {1..60}; do
    if "${dc[@]}" exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready',timeout=5)" >/dev/null 2>&1; then break; fi
    if test "$attempt" = 60; then echo "ROLLBACK_READINESS_FAILED"; exit 1; fi
    sleep 2
done
"${dc[@]}" up -d --no-build --no-deps caddy
domain=$(python3 -c "from pathlib import Path; import sys; print(next(x.split('=',1)[1].strip() for x in Path(sys.argv[1]).read_text().splitlines() if x.startswith('APP_DOMAIN=')))" "$state/env")
curl --retry 12 --retry-delay 5 --retry-all-errors --max-time 10 --fail --silent --show-error "https://${domain}/login" >/dev/null
echo "Images, readiness and trusted HTTPS restored; schema rollback is manual."
