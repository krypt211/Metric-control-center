#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
test -f .env.production || { echo "Configure .env.production.example first" >&2; exit 2; }
docker compose version >/dev/null
test -f config/metricflow-schema.json || { echo "Copy the verified READ schema to config/metricflow-schema.json" >&2; exit 2; }
python3 scripts/prepare_secrets.py
mkdir -p backups .deploy-state
chmod 700 backups .deploy-state
dc=(docker compose --env-file .env.production -f docker-compose.production.yml)
"${dc[@]}" config --quiet
"${dc[@]}" build migrate backend frontend backup
"${dc[@]}" up -d --wait --wait-timeout 120 postgres redis
"${dc[@]}" up --no-deps --no-build --force-recreate --exit-code-from migrate migrate
"${dc[@]}" run --rm --no-deps backend python -m services.auth.bootstrap
"${dc[@]}" up -d --no-deps --no-build backend worker scheduler frontend caddy backup-job
bash scripts/check_server.sh
