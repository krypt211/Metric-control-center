# META JOB LIFECYCLE REPORT

Date: 2026-10-13, Europe/Moscow. PostgreSQL head:0014_meta_jobs.
Scope: Meta READ jobs only. Existing ProviderJob/Celery ingestion queue retained.

## Final statuses

- META JOB LIFECYCLE: READY (LOCAL/MOCK AND ISOLATED POSTGRESQL).
- META RATE LIMIT PROTECTION: READY LOCAL.
- META LIVE CONNECTION: DISABLED.
- METRICFLOW READ: PRESERVED.
- METRICFLOW WRITE: PRESERVED, LIVE BLOCKED.
- ADVERTISING WRITE REQUESTS:0.

ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false. No Meta token connected or real Meta sync.
Meta daily cap unchanged. No Docker volumes removed; other projects untouched.

## Audit and architecture

The original durable queue lacked deadlines/semantic keys/owned leases.
Periodic Meta syncs bypassed ProviderJob; manual recovery requeued old claims.
HTTP FIFO/pacing/cooldown/meter already existed and are retained.
Periodic Meta tasks now enqueue ProviderJob and use the existing dispatcher.
There is no additional broker, queue service, scheduler or advertising dispatcher.

Before changes the working inventory was one SUCCEEDED Meta job (2026-10-09)
and12 SUCCEEDED MetricFlow jobs. Active historical Meta jobs:0.
No historical job was automatically assigned a new deadline.

## Durable TTL and legacy policy

Nullable additive fields: purpose, deadline, dedup/active keys, account scope,
request/config snapshot, timezone/slot, owner/lease, cancel request/recovery count.
Separate provider_job_audit retains transitions and reasons.
Defaults in seconds: today540, yesterday3300, last7 82800, manual1800, health300.
META_JOB_TTL_*_SECONDS are configurable in backend/worker Compose.
Scheduler publishes existing expiry envelopes; producer defaults remain unchanged.
Queue limit20, owner lease240s, manual dedup interval60s. All values bounded.

Before each new HTTP attempt, including pages/retries, the worker checks
deadline, owner, cancellation, enabled state and configuration fingerprint.
Expiration commits EXPIRED (stored expired following existing status convention),
JOB_TTL_EXPIRED, audit and released owned job lease. No subsequent HTTP is sent.
Already started GET may finish; publication is fenced. Incomplete account windows
are not published. Existing completed READ facts are not retroactively deleted.

A delayed periodic message inherits its original Celery deadline/publication
period/slot. Worker arrival cannot give it a fresh TTL or move it to today's
window. An out-of-order old tick cannot supersede a newer queued tick.

Legacy rows without deadline are held, not replayed. Explicit review_legacy:
read-only inventory first; an inventory digest must still match before apply.
Only never-started queued rows with BOTH creation and period older than90days,
and no active sync lease, may become EXPIRED/LEGACY_REVIEWED_STALE_90D.
The180-day fixture passed this reviewed policy with0 HTTP.
Working active legacy inventory remains0; no real historical record changed.

## Semantic deduplication

Key includes workspace/provider, selected source-account scope, sync purpose,
exact dates, timezone, request schema/fields, configuration fingerprint/revision
and scheduling slot. Sync requires explicit selected Meta accounts (<=3).
Health is discovery-only and does not trigger catalogue/Insights sync.

PostgreSQL transaction advisory locks serialize enqueue/claim/cancel transitions.
Unique dedup index prevents duplicate messages in the same refresh slot.
Partial unique active-key index prevents equivalent simultaneous active jobs.
Terminal history retains the slot key, preventing sequential same-slot replay.
New interval permits legitimate refresh. Different periods/accounts/workspaces
are not collapsed. Newer periodic/config generations supersede pending jobs
with audit; running generations stop cooperatively. Backpressure returns429
at the configured active-job bound. No frequency/cap increases are used.

## Cancellation, fencing and recovery

Pending cancellation commits CANCELLED/JOB_USER_CANCELLED and clears ownership.
Running cancellation returns CANCEL_REQUESTED; it does not kill a worker/process
or retract an in-flight GET. Next checkpoint stops new pages/retries.
Publication fence uses the same transaction lock as cancellation/config changes.
Cancelled health jobs do not poison a healthy provider connection.
Credential replacement/disconnect use precise reasons and cooperative Meta stop.

Only one Meta job per workspace is claimed at a time. HTTP concurrency remains
one per app across workspaces. Job lease is renewed at each HTTP boundary;
240s exceeds the existing180s sync lease and35s request timeout.
A dead owner is recovered only while the job is fresh, with at most2 recoveries.
Stale jobs expire; old owner tokens fail. Expired sync leases alone are released.
A live sync overlap defers the fresh job instead of losing it.
Cooldown gates dispatch; deadline checks continue after restart/queue delays.

## Monitoring UI

Existing Meta settings now show pending/running/expired/cancelled/failed,
legacy held, oldest pending age, wait average/max, backlog, drain estimate,
queue saturation warning, reasons and deadline, with ADMIN/CSRF cancellation.
Wait metrics sample the latest1000 started jobs; history list latest40.
Counts remain workspace-scoped. Drain forecast uses local catalogue and weights,
excludes running remainder/network latency/cooldown, and is explicitly Estimated.
Current cooldown/last rate-limit incident remain in the HTTP usage panel.
Queue is shown only on usage tab; HTTP journal remains a separate view.
Widths1440/1024/768/390 passed without overflow;390 screenshot inspected.
No automatic pacing increase or Meta connection is added.

## Mock HTTP attempts by scenario

Measured via the retained HTTP Request Meter on SQLite and isolated PostgreSQL.
Fixture catalogue has one AD/account and fits one page; forecast catalogue differs.

| Scenario | HTTP attempts |
|---|---:|
|1 account complete sync|8|
|3 accounts complete sync|18|
|169 logical jobs/day, small fixture|1352|
|Duplicate tick + next slot allowed|8 total; duplicate adds0|
|Duplicate manual + next refresh allowed|8 total; duplicate adds0|
|180-day legacy inventory/review|0|
|Expired periodic|0|
|Expired manual|0|
|Running cancellation after first response|1|
|Owner recovery/new claim, stale owner rejected|0|
|Fresh durable record survives new connection|0|
|Recovery limit reached|0|
|429, no retry|1|
|Cooldown survives new connection|0 new|
|Pending cancellation/no later claim|0|
|Running expiry after first response|1|
|Queue saturation/backpressure|0|
|Account isolation|0|
|Workspace isolation|0|
|Pending supersede/config invalidation|0|
|Pagination|9; one page>1 attempt|
|Transient retry|9; one attempt>1|
|Original periodic deadline retained|0|
|Out-of-order tick|0|
|Health cancellation without poisoning|1|
|8 independent enqueue processes|0;1 created/7 deduplicated|
|Independent claim/cancel process race|0; final CANCELLED|

Additional real isolated component restart:
Redis, worker and scheduler restarted; Redis AOF survived.
Seed429:1 mock attempt persisted. Expired job after restart:0 HTTP.
Fresh job recovered once and completed:3 mock HTTP attempts.
Meter total after restart:4. Persisted cooldown blocked another request:0 new.
Production components were not restarted for this restart scenario.
Actual working workspace Meta HTTP attempts remain0.

All transport callbacks assert GET. No PAUSE/ENABLE/BUDGET endpoint called.

## Calculated schedule and forecast

Calculated:144 today +24 yesterday +1 reconciliation=169 Meta tasks/day.
Meta disabled means these scheduled opportunities send0 real Meta HTTP.
Forecast uses saved8-account catalogue average:7 campaigns,20 adsets,22 ads,
120 creatives; pages100;3/3/9-date envelopes for today/yesterday/last7.
Full roster/auth assumption3 reads. Four catalogues need5 pages/account.
Insights pacing weight2 is local policy, not a provider complexity score.

|Selected accounts|HTTP/day no retry|Today slot cost|Daily pacing occupancy|
|---:|---:|---:|---:|
|1|1522|100s|16920s,19.6%|
|3/max allowed|3552|240s|40620s,47.0%|

Forecast baseline169 jobs drains without accumulating, max waits60/240s.
It excludes real latency/retries/cooldown/manual work. Large catalogues can
still exceed the10-minute interval; deadlines/backpressure bound useful work.
Minimum real pacing remains10s; no local Meta cap change. Worst retry bound
can exceed local cap and is stopped, not justified by a larger provider tariff.
Rate-limit root cause/tier/live headers are not established by mocks.

## Acceptance and preservation

Full backend:575 passed,1 skipped,78 subtests. Later targeted health/tick checks
passed. All25 lifecycle scenarios passed across SQLite/PostgreSQL batches,
including actual process dedup/claim-cancel tests.
Frontend35 unit tests, TypeScript and production build passed.
Isolated Playwright8/8 includes queue cancellation and four widths.
Working Playwright: navigation7/7, Economics4/4, Rules3/3, Manual Control5/5.
Rules first combined run hit the existing local240/min HTTP limiter (429);
separate Rules rerun passed without changing/resetting limits or weakening tests.
Navigation, combined Economics/Rules, separate Rules and Manual Control each
compared69 protected tables: no differences, advertising execution delta0.
Manual tests cover PAUSE/ENABLE drafts, Rule Engine decisions, permissions and
DRY_RUN simulation. No advertising transport mutation was sent.

Final runtime at2026-10-13T07:22:15Z: one documented MetricFlow READ GET/me
succeeded using the existing READ client and existing local quota. Connection
revision1 unchanged. WRITE credential was neither checked nor accessed again.
Backend/Credential Manager/PostgreSQL/Redis healthy; frontend/worker/scheduler
running; migrate exited0. Readiness reports database/migrations/schema/Redis OK.
Meta disabled/disconnected. All four safety flags match the required values.

Backup:backups/meta-lifecycle-20261012_225132.dump; restore and migration rehearsal
passed, with67 existing data tables unchanged. Guarded repeat passed.
Working deployment also preserved67/67 old data tables/fields; only nullable
job columns and audit table added. READ/WRITE credential tables, connections
and READ/WRITE cipher files unchanged. Advertising execution delta0.
Credential Manager source/configuration was not changed or restarted.
Worker/scheduler resumed; migration exit0; head0014. No destructive downgrade.
Test schemas/restored DB/Redis volume retained; test stack stopped without -v.

## Remaining blockers / first limited Meta READ test

Local lifecycle and rate controls are READY. Live behavior remains UNVERIFIED.
Need separate explicit permission, valid approved app/token/ads_read/object access,
confirmed API version/tier/header limits, selected one account and small period.
Before a controlled first READ, explicitly decide whether periodic Meta scheduling
is held; do not silently start169 daily jobs when only a bounded probe is approved.
Watch actual headers, latency, attempts, queue/cooldown and stop criteria.
Unknown provider quotas and timeout/permission behavior cannot be inferred from
local counts. Any advertising WRITE remains separately blocked.


## MetricFlow LIVE WRITE remains blocked

Prior credential acceptance remains unchanged; this phase did not replace keys,
rotate credentials or introduce an advertising HTTP adapter. Stored scope evidence
and its timestamp are in WRITE_KEY_ACCEPTANCE_AND_META_PACING_REPORT.md.
This is preservation evidence, not a fresh WRITE-key acceptance request.

Still need confirmed provider documentation for entity_id namespace, exact
PAUSE_AD/ENABLE_AD URL/method/body, success/error/unknown-outcome schemas,
permissions on the chosen AD, configured/effective status fields, idempotency,
timeout reconciliation and bounded readback verification. Existing entities:write
scope does not establish campaigns:write or permissions on an individual AD.
Do not implement these contracts by inference. Obtain the missing provider
specification and object permission evidence, then validate only with mocks;
a first real advertising WRITE additionally needs separate explicit authorization.

## Evidence locations

Ignored .tools/meta-lifecycle-* artifacts retain inventory, backup/restore,
migration rehearsals, backend/frontend results, actual mock attempt counts,
PostgreSQL process races, isolated restart evidence and final runtime checks.
.tools/navigation-meta-lifecycle-*-integrity.json retains working table hashes.
The original restored database, test schemas and isolated Redis volume are retained.
