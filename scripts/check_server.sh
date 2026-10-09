#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
dc=(docker compose --env-file .env.production -f docker-compose.production.yml)
for attempt in {1..60}; do
    if "${dc[@]}" exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready',timeout=5)" >/dev/null 2>&1; then break; fi
    if test "$attempt" = 60; then echo "READINESS_FAILED"; exit 1; fi
    sleep 2
done
"${dc[@]}" exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready',timeout=10)"
domain=$(python3 -c "from pathlib import Path; print(next(x.split('=',1)[1].strip() for x in Path('.env.production').read_text().splitlines() if x.startswith('APP_DOMAIN=')))")
curl --retry 12 --retry-delay 5 --retry-all-errors --max-time 10 --fail --silent --show-error "https://${domain}/login" >/dev/null
location=$(curl --silent --show-error --head "http://${domain}/login")
printf '%s' "$location" | grep -Eiq '^HTTP/[^ ]+ (301|302|307|308)' || { echo "HTTP_REDIRECT_FAILED"; exit 1; }
"${dc[@]}" exec -T backend python -c "from redis import Redis; import os; r=Redis.from_url(os.environ['CELERY_BROKER_URL']); assert r.get('mcc:heartbeat:worker') and r.get('mcc:heartbeat:scheduler')"
echo "Readiness, trusted HTTPS, redirect and heartbeat: PASS"
