# META CONTROLLED READ PILOT REPORT

Date: 2026-10-13. This phase prepares READ only; it does not authorize LIVE.

## Status

- META CONTROLLED READ PILOT: READY LOCAL/MOCK; LIVE prerequisites remain blocked.
- META LIVE READ: NOT EXECUTED.
- METRICFLOW READ: PRESERVED.
- METRICFLOW WRITE: PRESERVED, LIVE BLOCKED.
- ADVERTISING WRITE REQUESTS: 0.

ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false;
AI_AUTOPILOT_ALLOWED=false. No Meta token was created or connected.
Existing MetricFlow READ/WRITE keys and credential manager are not replaced.

## Architecture and audit

Existing MetaMarketingProvider, fixed-origin GET-only MetaClient, Request Meter,
app FIFO/rate limiter, ProviderManager and ProviderJob/Celery queue are reused.
The additive meta_pilot_sessions table stores immutable prepared session scope,
credential revision, attempt budget, deadline, status and safe result summary.
It is session state, not another queue. An approved session creates one ProviderJob.
Migration 0015_meta_pilot follows 0014_meta_jobs and performs no data conversion.

META_CONTROLLED_READ_PILOT=true is the default in both Compose deployments,
including backend, READ worker and scheduler. There are two separate deployment
gates: META_PILOT_AUTHORIZED_SESSION_ID and META_PILOT_CONFIRMED_GRAPH_VERSION.
Both are empty by default. Neither can be set through frontend/API input.
Saving a prepared session is not authorization. No UI LIVE-start button exists.
The start endpoint requires ADMIN, CSRF, exact deployment-approved session ID,
safe flags, matching credential revision, confirmed pinned version and credentials.

Saving Meta credentials under this mode encrypts them in the existing vault,
keeps ProviderConnection.enabled=false and queues no automatic health request.
Standard Meta health/manual sync, provider creation, enqueue, scheduled tasks
and replayed legacy worker jobs are blocked server-side. MetricFlow is unaffected.

## Scope and future GET sequence

One explicit external account act_ID; exactly 1–3 inclusive days, not future dates.
The account ID is immutable per session. A second active session is rejected.
Another account or changed scope requires a new session ID and new authorization.
No me/adaccounts roster discovery is performed by the pilot.

|Step|Future GET|Minimum attempts|Stop checks|
|---|---|---:|---|
|0|Local credentials presence and pinned-version gate|0|Missing credentials/version approval, unsafe flags|
|1|/debug_token, existing app-auth token verifier|1|is_valid/app_id/expiry/scopes|
|2|/me/permissions, fields=permission,status|1|ads_read must be granted; pagination consumes budget|
|3|/act_ID, fields=id,account_id,name,account_status,currency,timezone_name|1|Exact ID/account_id binding, active account|
|4|/act_ID/campaigns|1|Existing provider fields, matching account, pages/rows bounded|
|5|/act_ID/adsets|1|Same checks|
|6|/act_ID/ads|1|Same checks|
|7|/act_ID/adcreatives|1|Same checks|
|8|/act_ID/insights|1|Explicit since/until, level=ad, daily rows, existing attribution|
|9|Local session report and stop|0|No standard scheduler activation|

Minimum: **8 physical GET attempts**, assuming one page per edge, no retry.
Four catalog edges and Insights retain the existing MetaMarketingProvider fields.
Insights uses time_increment=1, existing 7d_click/1d_view attribution and impression
report time. No breakdowns, async job creation, batch, token refresh or WRITE.
All additional pages and retries consume the same session budget. No per-AD
Insights fan-out. Headers are read from these responses; they cost no extra HTTP.
The pilot validates complete catalog/Insights mappings but only stores safe counts
and verification summary; it does not replace working advertising facts.

## Budgets, pacing, cancellation and failure policy

Session cap defaults20 and is bounded1..20. The cap cannot be raised by input.
If the complete READ sequence needs another attempt after the cap, stop with
META_PILOT_ATTEMPT_LIMIT; never expand quota automatically. A configured cap7
was measured to stop after7 attempts before completion; explain minimum8.

The counter increment and MetaRequestAttempt insert occur in one PostgreSQL
transaction under the existing workspace advisory lock. Each physical attempt,
including retries/timeouts, reserves budget immediately before HTTP dispatch.
Reservations surviving a crash count conservatively even if delivery is unknown.
Restart never resets used_attempts. An active owner lease lost after a crash stops
the pilot with META_PILOT_OWNER_LOST instead of replaying the whole session.
A previously approved queued session is only eligible before its durable deadline.

Global local daily cap, app FIFO, concurrency1, minimum interval10 seconds,
Insights pacing weight2 and persisted cooldown remain in place. Mock transports
alone use interval0 to avoid consuming wall-clock/provider quota in tests.
No increase of local Meta cap or claimed provider quota was introduced.
No automatic retry on token/permission/rate errors. Other transient/transport
failures retain the existing maximum2 retries, counted physically.
A page edge is capped20 pages and2000 rows; the session cap is stricter.

Timeout is configurable30..900 seconds (default600), enforced by durable deadline
before each new attempt and final success publication. A request already in flight
can complete within the existing bounded35-second client timeout. No subsequent
attempt is allowed after deadline/cancellation; this is cooperative cancellation,
not a claim that an HTTP request already delivered can be recalled.
Queued cancellation is immediate; running cancellation is checked before next HTTP.
Session-specific authorization is rechecked before every attempt and at completion.
Revoked grant, credential revision change or account/path mismatch stops execution.
Meta429 persists cooldown and stops; permission/token/account/schema/unknown
critical response errors stop. Existing HTTP queue timeout also stops the session.
Pending/running historical Meta jobs must be explicitly reviewed/cancelled before
an approved pilot can be queued; preparation never drains or silently expires them.

## Scheduler management

The three Meta beat entries are removed under controlled mode. Stale broker ticks
are also rejected by the task itself. Dispatcher only selects purpose=pilot.
Ordinary jobs are held without applying a new TTL to legacy rows.
Stopping/completing a pilot does not alter the mode or enable Meta connection,
periodic schedule, Action Engine or advertising rules. Existing MetricFlow READ
schedule remains unchanged. No advertising automation is enabled.

## UI

Settings > Connections > Meta API includes “Тестовое READ-подключение”.
It shows chosen account/period, maximum/used attempts, credentials presence,
Graph version, confirmed header Access Tier or unknown, cooldown, status and
safe stop/error code. Preparation, refresh and cancellation are local actions.
Configuration does not grant LIVE permission; start remains gated on the server.

## Validation

Measured:
- Full backend:597 passed,1 skipped,78 subtests; final targeted pilot/API suite26/26.
- Isolated restored PostgreSQL:23 pilot +3 API tests passed,26 retained schemas.
- Independent8-process budget race:20 reservations/journal records,12 denied,
  0 HTTP. Rechecked after the bounded active-key hash correction.
- Frontend:35 unit tests, TypeScript and production build passed.
- Playwright integrations9/9; final pilot restart scenario passed again.
  Actual isolated backend restart preserved the prepared session, Meta attempt
  count and action execution count; four widths1440/1024/768/390 checked.
- Ruff/check-format passed for11 new/clean touched modules; source secret scan
  and staged diff review completed before the local commit.
- Docker backend/Credential Manager/PostgreSQL/Redis healthy; frontend/worker/
  scheduler running. Working migrate exited0, head0015_meta_pilot.
- Working deployment:68/68 pre-existing data tables unchanged; credential tables
  and all secret files unchanged, advertising execution delta0.
- Final MetricFlow READ GET/me succeeded at2026-10-13T09:54:06Z; READ connection
  revision1, stored WRITE revision1. WRITE credential was not accessed or checked.
- Existing Meta credentials are present, encrypted and locally decryptable.
  Configured Graph versionv26.0; token validity/READ permissions NOT CHECKED LIVE.
  Meta remains disabled/disconnected;0 actual Meta attempts; no pilot session;
  grant/version-confirmation empty; all three Meta beat entries absent.
  These credentials were preserved, not replaced or automatically validated.

|Mock scenario|Physical attempts|
|---|---:|
|Complete one-account minimum|8|
|Pagination exhausts cap|20|
|One transient retry|9|
|429 / permission / invalid / expired token|1 each|
|Unknown critical response|1|
|Account binding mismatch|3|
|Pending stale job, standard reads, second account, expired queued session|0 each|
|Restart with exhausted budget|0|
|Cooperative running cancellation|1|
|Running session deadline expires|1|
|Lost owner restart|0|
|Revoked session approval|1|
|Configured lower cap7|7; stopped, no quota expansion|
|Header/journal success|8|
|Version unconfirmed / invalid window / workspace mismatch|0|

Calculated minimum8 assumes one page per edge and no retries. Actual LIVE
pagination, latency, tier, effective permission and rate behavior remain unknown.
No mock count is described as a measured provider quota.

Migration rehearsed on mcc_integrations_meta_pilot_20261013_093800, restored from
backups/meta-pilot-20261013_093800.dump. All69 tables matched the initial restore;
all68 pre-existing data tables matched after migration (Alembic revision excluded).
Guarded repeat was ALREADY_CURRENT. Test schemas and volumes are retained.

## Documentation evidence and remaining LIVE blockers

Context7 official Meta Marketing API documentation confirms the selected-account
GET, Insights time_range and response usage/throttle headers:
- [Ad Account reference](https://developers.facebook.com/docs/marketing-api/reference/ad-account/)
- [Monitoring and analytics](https://developers.facebook.com/docs/marketing-api/get-started/ad-optimization-basics/monitoring-and-analytics/)
- [Insights best practices](https://developers.facebook.com/docs/marketing-api/insights/best-practices/)
- [Authentication](https://developers.facebook.com/docs/marketing-api/get-started/authentication/)

The existing connector token verifier is retained; its actual runtime token and
asset permissions have not been verified in this phase. Context7 did not establish
the installed credential's v26.0 compatibility. Direct official version/token
documentation fetches failed (unavailable/429 documentation pages, not Meta API).
Do not infer live version/tier/permissions from fixtures or third-party mirrors.
META_PILOT_CONFIRMED_GRAPH_VERSION stays empty until official version evidence
for the selected app/fields is supplied and reviewed.

Before LIVE: user must review the existing READ credential/app entitlement,
one explicitly authorized external account, a small exact date range, official
pinned-version evidence, token type/app-review/ads_read entitlement and object
access. Access Tier remains UNKNOWN until confirmed headers/Meta evidence exist.
Local10-second pacing is not a guarantee against provider throttling.
There must be no unresolved active legacy Meta jobs, current cooldown or exhausted
global local quota. The session-specific deployment grant must remain empty until
separate explicit permission for this exact session/account/period/cap is received.

MetricFlow LIVE WRITE remains independently blocked by missing confirmed entity ID,
PAUSE/ENABLE request/response/error, object permissions, configured/effective status,
idempotency, timeout reconciliation and readback contracts. This phase does not
implement or test advertising mutations.

## Exact procedure for the first future LIVE READ

1. Leave the four safety flags unchanged and controlled mode true. Keep standard
   Meta disabled, routing/action provider unchanged and all grant variables empty.
2. Obtain/review official Graph version and READ/asset permission evidence.
   Review existing encrypted READ credentials and stored-only/offline status.
   If replacement is necessary, use the existing Meta settings; do not rotate by default.
   Never put credentials in commands, screenshots, logs or this report.
3. Review old Meta queue, current cooldown/global budget. Cancel only explicitly
   reviewed stale jobs using the existing authenticated cancellation API.
4. Prepare one account and preferably one completed day, cap20, timeout600.
   Record immutable session ID/revision and calculated minimum8 requests.
5. Present that exact account/period/session/cap/version and stop conditions to
   the user and receive separate explicit authorization. Nothing here grants it.
6. Only then have the server operator set META_PILOT_AUTHORIZED_SESSION_ID to
   that exact UUID and META_PILOT_CONFIRMED_GRAPH_VERSION to the reviewed version
   for backend/READ worker. Leave Meta connection disabled and controlled mode true.
7. As ADMIN with CSRF, invoke the local /api/admin/providers/meta/pilot/UUID/start
   once. Existing ProviderJob dispatcher runs only this approved pilot. Do not
   call generic check/sync or trigger standard backfill.
8. Observe attempts, headers/tier, cooldown, deadline and stop reason. Cancel at
   any unexpected scope/error. No quota expansion or broad retry/restart.
9. Export a sanitized report (attempts/status/errors/counts only), remove the
   session grant from deployment and verify standard Meta scheduler still held.
   A new scope or another test requires a new session and new authorization.
