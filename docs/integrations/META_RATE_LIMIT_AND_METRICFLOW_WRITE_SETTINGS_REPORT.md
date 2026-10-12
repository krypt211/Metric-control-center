# META RATE LIMIT AND METRICFLOW WRITE SETTINGS REPORT

Verified 2026-10-12/13. Metric Control Center.

## Final statuses

- META API REQUEST AUDIT: PARTIAL (legacy wire evidence unavailable).
- META API RATE LIMIT PROTECTION: READY LOCAL/MOCK; LIVE UNVERIFIED.
- METRICFLOW WRITE KEY SETTINGS: READY.
- METRICFLOW WRITE CREDENTIAL: NOT CONFIGURED.
- METRICFLOW LIVE ACTIONS / Phase 4B: BLOCKED.
- Real advertising WRITE requests: 0.

ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false. Meta disabled; existing MetricFlow READ preserved.
Phase 3.1 unchanged. Phase 4A local preparation/simulation does not grant LIVE.

## META API REQUEST AUDIT

2026-10-09 UTC history: 08:10 partial/107 reservations/107 pages;
08:20 running/100 reservations/0 pages; 08:30 partial/60 reservations/59 pages,
META_RATE_LIMIT. ApiQuota recorded 270 reservations: runs account for 267,
3 unattributed; blocked_until 08:46:55.769964 UTC. Reservations are not
proven HTTP attempts. Old records lack endpoint/status/code/subcode/headers,
account/app/retry. Exact historical cause UNKNOWN. Running does not prove overlap.

Existing connector retained: health debug-token + permissions + accounts;
full sync accounts + campaigns/adsets/ads/creatives/AD-level Insights per account.
No per-ad Insights calls. Pages of 100. Dashboard/filter/refresh/account switch
use local DB. Existing Meta catalogue: 8 accounts, 55 campaigns, 154 adsets,
169 ads, 958 creatives. No new Meta connection or real Meta requests.

## Documentation and limits

[Official Meta announcement, May 4 2026](https://developers.meta.com/blog/updates-to-ads-management-standard-access-feature/):
AMSA renamed Marketing API Access Tier; Limited/Full replace Standard/Advanced;
Full eligibility includes 500 calls/15 days and <15% errors among last 500 calls.
These are eligibility rules, not a daily quota. Current app tier UNKNOWN.
Context7 Marketing API docs consulted; direct Graph docs partly 429/cache miss.

Allowlisted X-App-Usage, X-Ad-Account-Usage, X-Business-Use-Case-Usage,
X-FB-Ads-Insights-Throttle numeric fields retained. Call/CPU/time values are
utilization percentages, not remaining requests. Raw headers/URLs/query/tokens
and bodies excluded. estimated_time_to_regain_access units unconfirmed:
not used to calculate cooldown. Old labels do not establish current live tier.

## RATE LIMIT PROTECTION

Durable PostgreSQL HTTP attempt meter: UTC, app/account, endpoint category,
method, operation/run, attempt/page, status/duration/retry/code/subcode,
usage/local complexity/source/outcome. Unfinished STARTED is unknown outcome.
Shared advisory lock + FIFO queue + lease; app concurrency 1 => account <=1.
Default interval 10 seconds, lease 90s, HTTP timeout 35s, queue wait <=90s/TTL120s.
Rate codes 4/17/32/613/80004: minimum 900s cooldown or longer Retry-After.
Usage >=85%: local minimum 60s pause. Policy is conservative, not Meta guarantee.
Headers timestamp changes only when headers arrive. At most 2 transient retries;
rate/token/permission failures do not loop. Retry-After dates/seconds respected.
Concurrent identical GETs coalesced within same client; no permanent stale cache.
Scheduler lease retained. Max 3 selected accounts, workspace IDs validated.
Insights fields, attribution, economic formulas and date semantics preserved.

## Forecast and UI

Network-free estimates distinguish Measured/Calculated/Estimated.
Missing telemetry is UNKNOWN/NOT_MEASURED. One-page lower bound: 3+5N.

| Accounts | Minimum | Estimated today/yesterday | 7 days | 30 days |
|---:|---:|---:|---:|---:|
|1|8|9|10|15|
|3|18|21|24|39|
|10|53|63|73|123|
|50|253|303|353|603|

Estimates use average saved 8-account catalogue and explicit Insights assumptions,
not live quotas. Empty catalogue gives qualified assumptions. Existing schedule:
today every 10min, yesterday hourly, last7 daily; today/last7 envelope +/-1day.
Multiplying sync cost by scheduled runs is a scenario, not future measurement.
Russian panels in existing /settings/connections: utilization/cooldown/unknown
tier, filtered paginated log, offline forecast, pacing and searchable account
selection. Responsive 1440/1024/768/390: verified without document overflow.

## WRITE key security and API

Existing WriteCredentialVault reused: independent Fernet key, workspace/purpose
binding, encrypted DB row, revision CAS, delete tombstone, secret-free audit.
ADMIN/session/CSRF/Origin checked at backend and private credential-manager.
Validation errors never echo token. Service has no public port/docs; WRITE cipher
and restricted DB password absent from ordinary backend and READ workers.
Fixed private proxy hostname; no configurable forwarding origin.
Only internal encryption/DB secrets created; no real provider WRITE key.
DB role NOSUPERUSER: READ credentials SELECT=false, actions INSERT=false,
WRITE state UPDATE=true. READ encryption/revision/secret-file hashes preserved.
UI save/check/replace/delete clears password, confirms replacement/deletion,
returns fingerprint/revision/status only; no token in browser storage.

Check sends one documented GET /api/v1/me without retry, within shared800/day
budget/cooldown. Reported campaigns:write and paid access evaluated separately;
401/403/402/429/unavailable mapped safely. Scope does not prove asset access.
[MetricFlow docs](https://metricflowit.click/docs) do not establish complete
PAUSE_AD/ENABLE_AD ID/body/permissions/responses/errors/idempotency/verification
contract. Live wire adapter not invented. Credential checks tested on mocks only.

## Migration, Docker and data

Backup backups/integrations-before-20261012.dump restored to separate DB.
Frozen 0013 additive schema adds 6 tables. Rehearsal upgrade/repeat guard passed;
61 preexisting data tables unchanged. Working guarded migration also61/61 intact,
revision0013_integrations, total68 tables; READ secret hashes unchanged;
advertising execution delta0. Migration container exit0 replaces previous255.
No volumes deleted; other Docker projects untouched. Worker/scheduler resumed.
Deploy scripts build migration image, guard upgrades and provision restricted role.
Working WRITE state absent. Private credential service healthy after deployment.

## Validation

Backend full:522 passed,1 skipped,78 subtests. Final security:84 passed.
Scheduler overlap/large-roster:2 passed. Frontend35 unit tests, TS/build passed.
Isolated Chromium/private mock service:7 passed,0 skipped; four widths checked.
PostgreSQL concurrency:8 save contenders =>1 success/7 CAS conflicts;
8 Meta mock contenders =>peak app concurrency1.
Backend covers CSRF/tamper/redaction; UI covers roles/lifecycle/READ preservation.
Working navigation:7 passed; Rule Engine:3 passed; economics:4 passed.
Each regression preserved all68 tables, execution delta0.
Ruff/check-format, secret scan, dev/prod Compose and deploy shell syntax passed.
Backend/private credential service/PostgreSQL/Redis healthy; frontend and
READ worker/scheduler running; Meta disconnected, MetricFlow READ healthy.
First run failed only obsolete fixture migration allowlist; now accepts0013.
Integration E2E requires INTEGRATION_ACCEPTANCE=true and isolated mock stack;
ordinary suite explicitly skips it. A second fresh mock workspace rerun:7 passed.
Evidence in ignored .tools; no secrets reported.

Reproduce after an independent restore migrated to0013 and local images built:

```powershell
.venv\Scripts\python -m scripts.prepare_integration_acceptance mcc_integrations_RESTORED_DB
$env:INTEGRATION_ACCEPTANCE="true"
$env:UI_BASE_URL="http://127.0.0.1:3001"
# Set PATH to Node24 and PLAYWRIGHT_BROWSERS_PATH as locally configured.
cd frontend
npx playwright test e2e/integration-settings.spec.mjs
cd ..
docker compose -f .tools/integrations-acceptance.yml down
```

The harness refuses production database names, uses integration-ui-* workspace
and mock-only private service. No working provider credentials are used; down
does not remove volumes. Restore/backup is retained for inspection.

## HOW TO ADD WRITE KEY

1. ADMIN opens /settings/connections and independent WRITE card.
2. User enters separately obtained key; save encrypts it without changing READ.
3. Check performs GET/me within current quota; examine scope and paid access.
4. Verify permissions for one specific object using confirmed documentation.
5. Obtain full pause/enable and result-verification contract; rerun mock acceptance.
6. A real single-object test requires separate explicit authorization and recovery plan.

## Exact blockers for first controlled LIVE test

WRITE credential absent; scope/paid access UNKNOWN; object permissions UNVERIFIED.
Full PAUSE_AD/ENABLE_AD wire contract and verification/idempotency unconfirmed.
ACTIONS_ENABLED=false and LOCAL_READ_ONLY=true remain fail-closed.
No separate authorization for real test; no agreed object/recovery procedure.
User must provide official specification/support evidence, obtain separate key if
needed, and select a test object. Meta live tier/permissions remain unverified;
legacy rate-limit root cause cannot be reconstructed from historical records.
