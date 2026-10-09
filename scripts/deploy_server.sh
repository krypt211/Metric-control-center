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
"${dc[@]}" build backend frontend backup
"${dc[@]}" up -d postgres redis
"${dc[@]}" run --rm migrate
"${dc[@]}" run --rm backend python -m services.auth.bootstrap
"${dc[@]}" up -d
bash scripts/check_server.sh
