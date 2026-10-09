#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
revision=${1:?Usage: bash scripts/deploy_update.sh EXISTING_GIT_REVISION}
git rev-parse --verify "${revision}^{commit}" >/dev/null
test -z "$(git status --porcelain --untracked-files=no)" || { echo "Tracked changes; aborting"; exit 2; }
mkdir -p .deploy-state
dc=(docker compose --env-file .env.production -f docker-compose.production.yml)
"${dc[@]}" run --rm backup backup
stamp=$(date -u +%Y%m%dT%H%M%SZ)
state=".deploy-state/$stamp"
mkdir -m 700 "$state"
cp docker-compose.production.yml "$state/compose.yml"
cp .env.production "$state/env"
git rev-parse HEAD > "$state/revision"
for service in backend frontend worker scheduler; do
    id=$("${dc[@]}" ps -q "$service")
    image=$(docker inspect -f '{{.Image}}' "$id")
    docker tag "$image" "mcc-rollback-${service}:$stamp"
done
git checkout --detach "$revision"
"${dc[@]}" build backend frontend backup
"${dc[@]}" stop caddy frontend backend worker scheduler
"${dc[@]}" run --rm migrate
"${dc[@]}" up -d
bash scripts/check_server.sh
echo "Update verified. Previous images use timestamp: $stamp"
